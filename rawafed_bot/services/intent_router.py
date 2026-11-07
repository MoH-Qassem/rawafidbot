"""Local Arabic intent routing for group accountant chat (no external AI)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.transaction import Transaction
from rawafed_bot.services.addressing import strip_address_prefix
from rawafed_bot.services.contribution_service import ContributionService
from rawafed_bot.services.nl_operation_parser import NLOperationParser, ParsedOperation
from rawafed_bot.services.permission_service import PermissionService
from rawafed_bot.services.permissions_catalog import (
    PAY_CONTRIBUTION,
    VIEW_CASHBOX,
    VIEW_DEBTS,
    VIEW_HISTORY,
    VIEW_MEMBERS,
    VIEW_REPORTS,
)
from rawafed_bot.services.query_service import QueryService
from rawafed_bot.services.report_service import ReportService
from rawafed_bot.utils.money import find_currency, format_amount


@dataclass
class IntentResult:
    intent: str
    reply: str
    data: dict | None = None
    parsed_op: ParsedOperation | None = None


class IntentRouter:
    @staticmethod
    def route(
        db: Session,
        member: Member,
        text: str,
        caller_name: str,
    ) -> IntentResult:
        body = strip_address_prefix(text)
        low = body.lower()

        if not body or body in {"؟", "?", "مرحبا", "هلا", "السلام عليكم"}:
            return IntentResult(
                "help",
                f"أهلاً {caller_name}.\n"
                "يمكنني مساعدتك داخل المجموعة: رصيد الصندوق، تسجيل مصروف/إيداع/سحب، "
                "المساهمات، والتقارير. اكتب «يا محاسب، …» أو استخدم القائمة.",
            )

        # Cash box / balance — before write soft-start so «رصيد الصندوق» never becomes write
        if any(
            k in body
            for k in (
                "رصيد", "كم معنا", "الصندوق", "كم لدينا", "كم عندنا",
                "balance", "كم بالدولار", "كم بالليرة",
            )
        ) and not any(k in body for k in ("تسجيل", "سجل مصروف", "سجل إيداع", "سجل سحب", "سجّل")):
            if not PermissionService.has_permission(db, member, VIEW_CASHBOX):
                return IntentResult("denied", "⛔ ليست لديك صلاحية عرض الصندوق.")
            return IntentResult("cashbox", IntentRouter._cashbox(db, body, caller_name))

        # Write operations (expense / deposit / withdrawal) — including soft start
        parsed = NLOperationParser.parse(db, text)
        if parsed.op_type in {"expense", "deposit", "withdrawal"}:
            return IntentResult(
                "write_op",
                "",
                parsed_op=parsed,
            )
        if NLOperationParser.looks_like_write_start(text):
            # Ask for missing type/fields instead of «لم أفهم»
            if not parsed.op_type and "op_type" not in parsed.missing:
                parsed.missing.insert(0, "op_type")
            return IntentResult("write_op", "", parsed_op=parsed)

        # Top spender / totals
        if "أكثر" in body and any(k in body for k in ("أنفق", "صرف", "مصروف")):
            if not PermissionService.has_permission(db, member, VIEW_HISTORY):
                return IntentResult("denied", "⛔ ليست لديك صلاحية.")
            return IntentResult("top_spender", IntentRouter._top_spender(db))

        if any(k in body for k in ("مجموع المصاريف", "إجمالي المصاريف", "ما مجموع")):
            if not PermissionService.has_permission(db, member, VIEW_REPORTS):
                return IntentResult("denied", "⛔ ليست لديك صلاحية التقارير.")
            return IntentResult("expense_total", ReportService.expenses_by_category(db)[:3500])

        # Today / month expenses
        if "مصاريف اليوم" in body or "مصروفات اليوم" in body:
            if not PermissionService.has_permission(db, member, VIEW_HISTORY):
                return IntentResult("denied", "⛔ ليست لديك صلاحية.")
            return IntentResult("today", IntentRouter._period_expenses(db, days=0))

        if "هذا الشهر" in body and any(k in body for k in ("مصاريف", "مصروف", "صرف")):
            if not PermissionService.has_permission(db, member, VIEW_HISTORY):
                return IntentResult("denied", "⛔ ليست لديك صلاحية.")
            target = IntentRouter._resolve_member_name(db, body)
            if target:
                return IntentResult(
                    "member_spend", IntentRouter._member_month_expenses(db, target)
                )
            return IntentResult("month", IntentRouter._period_expenses(db, month=True))

        # Last N operations
        if any(k in body for k in ("آخر عشر", "آخر 10", "سجل العمليات", "اعرض آخر")):
            if not PermissionService.has_permission(db, member, VIEW_HISTORY):
                return IntentResult("denied", "⛔ ليست لديك صلاحية.")
            return IntentResult("history", ReportService.history(db, limit=10)[:3500])

        # Contributions
        if any(k in body for k in ("مساهم", "من لم يسدد", "المتأخر", "التزام", "كم متبقي")):
            if not PermissionService.has_permission(db, member, PAY_CONTRIBUTION):
                return IntentResult("denied", "⛔ ليست لديك صلاحية عرض المساهمات.")
            return IntentResult("contributions", IntentRouter._contributions_summary(db))

        # Debts
        if any(k in body for k in ("دين", "مستحق", "ديون")):
            if not PermissionService.has_permission(db, member, VIEW_DEBTS):
                return IntentResult("denied", "⛔ ليست لديك صلاحية عرض الديون.")
            return IntentResult("debts", ReportService.debts_report(db)[:3500])

        # Member spending query
        if any(k in body for k in ("صرف", "مصروف", "مصاريف")) and any(
            k in body for k in ("كم", "عرض", "ماذا", "ما هي", "وضع", "اعرض")
        ):
            if not PermissionService.has_permission(db, member, VIEW_HISTORY) and not (
                PermissionService.has_permission(db, member, VIEW_MEMBERS)
            ):
                return IntentResult("denied", "⛔ ليست لديك صلاحية عرض المصروفات.")
            target = IntentRouter._resolve_member_name(db, body)
            if target:
                return IntentResult(
                    "member_spend",
                    IntentRouter._member_month_expenses(db, target),
                )
            return IntentResult(
                "ask",
                "حدد اسم العضو، مثال: اعرض مصاريف أحمد هذا الشهر.",
            )

        if any(k in body for k in ("تقرير", "ملخص")):
            if not PermissionService.has_permission(db, member, VIEW_REPORTS):
                return IntentResult("denied", "⛔ ليست لديك صلاحية التقارير.")
            return IntentResult("report", ReportService.cash_box_report(db)[:3500])

        if any(k in low for k in ("ساعد", "help", "ماذا تستطيع", "كيف", "دليل")):
            return IntentResult(
                "help",
                "أمثلة داخل المجموعة:\n"
                "• يا محاسب، كم رصيد الصندوق؟\n"
                "• يا محاسب، سجل 50 ليرة سورية مصروف أوراق\n"
                "• يا محاسب، سجل إيداع 500 دولار\n"
                "• يا محاسب، من لم يسدد المساهمة؟\n"
                "أو افتح «📖 دليل الاستخدام والمزايا» من القائمة.",
            )

        return IntentResult(
            "unknown",
            f"{caller_name}، لم أفهم الطلب بوضوح.\n"
            "جرّب: رصيد الصندوق، أو «سجل مصروف …»، أو دليل الاستخدام.",
        )

    @staticmethod
    def _cashbox(db: Session, body: str, caller_name: str) -> str:
        currency = find_currency(db, body)
        rows = QueryService.cash_box_balances(db)
        if currency:
            row = next((r for r in rows if r["currency_id"] == currency.id), None)
            if not row:
                return f"لا يوجد حساب صندوق لعملة {currency.code}."
            return (
                f"💰 رصيد الصندوق ({currency.name_ar}): "
                f"{format_amount(row['balance'], currency)}"
            )
        lines = [f"💰 رصيد الصندوق — لـ {caller_name}:"]
        for r in rows:
            lines.append(format_amount(r["balance"], r["currency"]))
        if len(lines) == 1:
            lines.append("لا توجد أرصدة.")
        return "\n".join(lines)

    @staticmethod
    def _contributions_summary(db: Session) -> str:
        requests = ContributionService.list_requests(db)
        if not requests:
            return "لا توجد طلبات مساهمة حالياً."
        lines = ["📋 المساهمات غير المسددة بالكامل:"]
        any_open = False
        for req in requests[:10]:
            obs = ContributionService.get_obligations(db, req.id)
            for o in obs:
                remaining = o.amount - (o.paid_amount or 0)
                if remaining <= 0:
                    continue
                any_open = True
                mem = db.query(Member).filter_by(id=o.member_id).first()
                cur = next(
                    (c for c in QueryService.get_currencies(db) if c.id == req.currency_id),
                    None,
                )
                name = mem.get_display_name() if mem else str(o.member_id)
                amt = format_amount(remaining, cur) if cur else str(remaining)
                lines.append(f"• {name}: متبقي {amt} (طلب #{req.id})")
        if not any_open:
            return "جميع التزامات المساهمات المسجّلة مسددة أو لا يوجد متأخرون."
        return "\n".join(lines)

    @staticmethod
    def _resolve_member_name(db: Session, text: str) -> Optional[Member]:
        members = db.query(Member).filter_by(is_active=True).all()
        ranked = sorted(
            members,
            key=lambda m: len((m.display_name or m.telegram_full_name or "")),
            reverse=True,
        )
        for m in ranked:
            for cand in (m.display_name, m.telegram_full_name, m.telegram_username):
                if cand and cand.strip() and cand.strip() in text:
                    return m
        return None

    @staticmethod
    def _member_month_expenses(db: Session, member: Member) -> str:
        now = datetime.utcnow()
        start = datetime(now.year, now.month, 1)
        txs = (
            db.query(Transaction)
            .filter(
                Transaction.member_id == member.id,
                Transaction.transaction_type.in_(
                    ["expense", "personal_expense", "advance_settlement"]
                ),
                Transaction.status == "active",
                Transaction.created_at >= start,
            )
            .all()
        )
        if not txs:
            return f"لا مصروفات مسجّلة لـ {member.get_display_name()} هذا الشهر."
        by_cur: dict[int, int] = {}
        for tx in txs:
            by_cur[tx.currency_id] = by_cur.get(tx.currency_id, 0) + tx.amount
        lines = [f"مصروفات {member.get_display_name()} هذا الشهر:"]
        for cid, amt in by_cur.items():
            cur = next((c for c in QueryService.get_currencies(db) if c.id == cid), None)
            lines.append(format_amount(amt, cur) if cur else str(amt))
        return "\n".join(lines)

    @staticmethod
    def _period_expenses(db: Session, days: int = 0, month: bool = False) -> str:
        now = datetime.utcnow()
        if month:
            start = datetime(now.year, now.month, 1)
            title = "مصروفات هذا الشهر"
        else:
            start = datetime(now.year, now.month, now.day)
            title = "مصروفات اليوم"
        txs = (
            db.query(Transaction)
            .filter(
                Transaction.transaction_type.in_(
                    ["expense", "personal_expense", "advance_settlement"]
                ),
                Transaction.status == "active",
                Transaction.created_at >= start,
            )
            .all()
        )
        if not txs:
            return f"لا {title} مسجّلة."
        by_cur: dict[int, int] = {}
        for tx in txs:
            by_cur[tx.currency_id] = by_cur.get(tx.currency_id, 0) + tx.amount
        lines = [f"{title}:"]
        for cid, amt in by_cur.items():
            cur = next((c for c in QueryService.get_currencies(db) if c.id == cid), None)
            lines.append(format_amount(amt, cur) if cur else str(amt))
        return "\n".join(lines)

    @staticmethod
    def _top_spender(db: Session) -> str:
        now = datetime.utcnow()
        start = datetime(now.year, now.month, 1)
        txs = (
            db.query(Transaction)
            .filter(
                Transaction.transaction_type.in_(["expense", "personal_expense"]),
                Transaction.status == "active",
                Transaction.created_at >= start,
            )
            .all()
        )
        if not txs:
            return "لا مصروفات هذا الشهر للمقارنة."
        # Per member per currency — report separately without converting
        from collections import defaultdict
        totals = defaultdict(lambda: defaultdict(int))
        for tx in txs:
            totals[tx.member_id][tx.currency_id] += tx.amount
        lines = ["أكثر الأعضاء إنفاقاً هذا الشهر (حسب كل عملة):"]
        for mid, by_cur in totals.items():
            mem = db.query(Member).filter_by(id=mid).first()
            name = mem.get_display_name() if mem else str(mid)
            parts = []
            for cid, amt in by_cur.items():
                cur = next((c for c in QueryService.get_currencies(db) if c.id == cid), None)
                parts.append(format_amount(amt, cur) if cur else str(amt))
            lines.append(f"• {name}: " + " | ".join(parts))
        return "\n".join(lines)
