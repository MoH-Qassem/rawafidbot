"""Parse Arabic/English natural-language financial requests (no external AI)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from rawafed_bot.database.models.expense_category import ExpenseCategory
from rawafed_bot.services.addressing import strip_address_prefix
from rawafed_bot.utils.money import _ARABIC_DIGIT_MAP, find_currency, parse_user_amount
from rawafed_bot.utils.money import MoneyError

_AMOUNT_RE = re.compile(
    r"([0-9٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹]+(?:[.,٬،][0-9٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹]+)?)"
)

EXPENSE_WORDS = ("مصروف", "مصاريف", "نفقة", "صرفت", "صرف", "سجل مصروف", "سجّل مصروف")
DEPOSIT_WORDS = ("إيداع", "ايداع", "أودع", "اودع", "سجل إيداع", "سجّل إيداع")
WITHDRAW_WORDS = ("سحب", "اسحب", "سجل سحب", "سجّل سحب")
DEBT_WORDS = ("سداد دين", "تسديد دين", "سدد دين", "سداد مستحق")

NOISE = re.compile(
    r"(?:يا\s+)?محاسب|سجل|سجّل|تسجيل|من فضلك|رجاءً|رجاء|من فضلك|على|شراء|بخصوص",
    re.UNICODE,
)


@dataclass
class ParsedOperation:
    op_type: Optional[str] = None  # expense | deposit | withdrawal | debt_repay
    amount_text: Optional[str] = None
    amount_minor: Optional[int] = None
    currency_id: Optional[int] = None
    currency_code: Optional[str] = None
    description: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    missing: List[str] = field(default_factory=list)
    confidence: float = 0.0


class NLOperationParser:
    @staticmethod
    def detect_type(text: str) -> Optional[str]:
        t = text or ""
        if any(w in t for w in DEBT_WORDS):
            return "debt_repay"
        if any(w in t for w in DEPOSIT_WORDS):
            return "deposit"
        if any(w in t for w in WITHDRAW_WORDS) and "مصروف" not in t:
            return "withdrawal"
        if any(w in t for w in EXPENSE_WORDS):
            return "expense"
        # "صرفت 75 دولاراً على ..."
        if re.search(r"صرف\w*\s+\d", t.translate(_ARABIC_DIGIT_MAP)) or "صرفت" in t:
            return "expense"
        return None

    @staticmethod
    def parse(db: Session, text: str) -> ParsedOperation:
        body = strip_address_prefix(text or "")
        result = ParsedOperation()
        result.op_type = NLOperationParser.detect_type(body)
        if not result.op_type:
            result.missing.append("op_type")
            return result

        # Amount
        ascii_body = body.translate(_ARABIC_DIGIT_MAP)
        m = _AMOUNT_RE.search(ascii_body)
        if m:
            result.amount_text = m.group(1)

        # Currency
        cur = find_currency(db, body)
        if cur:
            result.currency_id = cur.id
            result.currency_code = cur.code

        # Category match for expenses
        if result.op_type == "expense":
            cats = db.query(ExpenseCategory).filter_by(is_active=True).all()
            # Prefer longest name match
            ranked = sorted(cats, key=lambda c: len(c.name or ""), reverse=True)
            for cat in ranked:
                if cat.name and cat.name in body:
                    result.category_id = cat.id
                    result.category_name = cat.name
                    break
            if not result.category_id:
                # fallback "أخرى"
                other = next((c for c in cats if c.name == "أخرى"), None)
                if other:
                    result.category_id = other.id
                    result.category_name = other.name

        # Description: strip known tokens
        desc = body
        if result.amount_text:
            desc = desc.replace(result.amount_text, " ")
            # also arabic form
            desc = re.sub(_AMOUNT_RE, " ", desc)
        for w in (
            "مصروف", "مصاريف", "نفقة", "صرفت", "صرف", "إيداع", "ايداع", "سحب",
            "سجل", "سجّل", "تسجيل", "دولار", "أمريكي", "ليرة", "سورية", "سوري",
            "تركية", "تركي", "USD", "SYP", "TRY", "$", "ل.س", "₺",
            "على", "شراء",
        ):
            desc = re.sub(re.escape(w), " ", desc, flags=re.IGNORECASE)
        if result.category_name:
            desc = desc.replace(result.category_name, " ")
        desc = NOISE.sub(" ", desc)
        desc = re.sub(r"\s+", " ", desc).strip(" ،,.-")
        if len(desc) >= 2:
            result.description = desc
        elif result.category_name:
            result.description = result.category_name
        elif result.op_type == "deposit":
            result.description = "إيداع"
        elif result.op_type == "withdrawal":
            result.description = "سحب"

        # Resolve amount if currency known
        if result.amount_text and result.currency_id:
            from rawafed_bot.database.models.currency import Currency
            currency = db.query(Currency).filter_by(id=result.currency_id).first()
            try:
                result.amount_minor = parse_user_amount(result.amount_text, currency)
            except MoneyError:
                result.amount_minor = None

        # Currency before amount so group collection can parse minor units next
        if not result.currency_id:
            result.missing.append("currency")
        if not result.amount_text:
            result.missing.append("amount")
        elif result.currency_id and not result.amount_minor:
            result.missing.append("amount")
        if result.op_type == "expense" and not result.category_id:
            result.missing.append("category")
        if not result.description:
            result.missing.append("description")

        result.confidence = 1.0 - (0.2 * len(result.missing))
        return result

    @staticmethod
    def summary_ar(parsed: ParsedOperation, member_name: str) -> str:
        type_ar = {
            "expense": "مصروف",
            "deposit": "إيداع",
            "withdrawal": "سحب",
            "debt_repay": "سداد دين",
        }.get(parsed.op_type or "", parsed.op_type or "—")
        cur = parsed.currency_code or "—"
        amt = parsed.amount_text or "—"
        desc = parsed.description or "—"
        cat = parsed.category_name or "—"
        lines = [
            "تم فهم طلبك — راجع الملخص قبل التأكيد:",
            f"• النوع: {type_ar}",
            f"• المبلغ: {amt}",
            f"• العملة: {cur}",
        ]
        if parsed.op_type == "expense":
            lines.append(f"• التصنيف: {cat}")
        lines.append(f"• الوصف: {desc}")
        lines.append(f"• المنفذ: {member_name}")
        return "\n".join(lines)
