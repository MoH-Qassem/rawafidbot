"""Financial report text + Excel generation."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from rawafed_bot.database.models.contribution import ContributionObligation, ContributionRequest
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.transaction import Transaction
from rawafed_bot.reports.excel_export import export_sheets
from rawafed_bot.services.query_service import QueryService
from rawafed_bot.utils.money import format_amount


TYPE_LABELS = {
    "deposit": "إيداع",
    "expense": "مصروف",
    "withdrawal": "سحب",
    "personal_expense": "مصروف على العضو",
    "debt_repayment": "تحصيل دين",
    "advance_issued": "عهدة",
    "advance_settlement": "تسوية عهدة",
    "reversal": "عكس قيد",
}


class ReportGenerator:
    @staticmethod
    def _fmt(amount: int, currency: Currency) -> str:
        return format_amount(amount, currency)

    @staticmethod
    def cash_box_text(db: Session) -> str:
        lines = ["💰 حالة الصندوق", "━━━━━━━━━━━━━━━━"]
        rows = list(QueryService.cash_box_balances(db))
        if not rows:
            lines.append("لا توجد أرصدة.")
            return "\n".join(lines)
        for row in rows:
            bal = row["balance"]
            label = ReportGenerator._fmt(bal, row["currency"])
            if bal < 0:
                lines.append(f"⚠️  {label}  (سالب)")
            else:
                lines.append(f"•  {label}")
        return "\n".join(lines)

    @staticmethod
    def full_summary_text(db: Session, date_from: datetime = None, date_to: datetime = None) -> str:
        parts = [ReportGenerator.cash_box_text(db), ""]
        parts.append("📉 المصروفات (ملخص الحسابات)")
        parts.append("────────────")
        for row in QueryService.expense_summary_balances(db):
            parts.append(ReportGenerator._fmt(row["balance"], row["currency"]))
        parts.append("")
        parts.append("📋 الديون النشطة")
        parts.append("────────────")
        debts = QueryService.active_debts(db)
        if not debts:
            parts.append("لا توجد ديون.")
        for d in debts:
            member = db.query(Member).filter_by(id=d.member_id).first()
            currency = db.query(Currency).filter_by(id=d.currency_id).first()
            parts.append(
                f"- {member.get_display_name() if member else d.member_id}: "
                f"{ReportGenerator._fmt(d.remaining, currency)}"
            )
        parts.append("")
        parts.append("📦 العهد المفتوحة")
        parts.append("────────────")
        advances = QueryService.open_advances(db)
        if not advances:
            parts.append("لا توجد عهد مفتوحة.")
        for a in advances:
            member = db.query(Member).filter_by(id=a.member_id).first()
            currency = db.query(Currency).filter_by(id=a.currency_id).first()
            parts.append(
                f"- #{a.id} {member.get_display_name() if member else a.member_id}: "
                f"{ReportGenerator._fmt(a.amount, currency)} ({a.status})"
            )
        return "\n".join(parts)

    @staticmethod
    def member_statement_text(db: Session, member_id: int) -> str:
        data = QueryService.member_statement(db, member_id)
        member = data["member"]
        lines = [f"👤 كشف حساب: {member.get_display_name() if member else member_id}", "────────────"]
        for row in data["balances"]:
            cur = row["currency"]
            lines.append(f"العملة: {cur.code if cur else row['currency_id']}")
            lines.append(f"  حقوق/مساهمات (دائن موجب): {ReportGenerator._fmt(row['equity'], cur)}")
            lines.append(f"  مستحقات على الشركة: {ReportGenerator._fmt(row['due'], cur)}")
            lines.append(f"  عهدة معلّقة: {ReportGenerator._fmt(row['advance'], cur)}")
        return "\n".join(lines)

    @staticmethod
    def export_period_excel(
        db: Session, date_from: datetime = None, date_to: datetime = None, title: str = "تقرير_مالي"
    ):
        cash_rows = []
        for row in QueryService.cash_box_balances(db):
            cash_rows.append([row["currency"].code, row["balance"] / (10 ** row["currency"].decimal_places)])

        tx_rows = []
        txs = QueryService.transactions(db, date_from=date_from, date_to=date_to, limit=5000)
        for tx in txs:
            currency = db.query(Currency).filter_by(id=tx.currency_id).first()
            member = db.query(Member).filter_by(id=tx.member_id).first()
            tx_rows.append([
                tx.id,
                tx.created_at.strftime("%Y-%m-%d %H:%M") if tx.created_at else "",
                TYPE_LABELS.get(tx.transaction_type, tx.transaction_type),
                currency.code if currency else tx.currency_id,
                tx.amount / (10 ** (currency.decimal_places if currency else 2)),
                member.get_display_name() if member else tx.member_id,
                tx.description or "",
                tx.status,
            ])

        debt_rows = []
        for d in QueryService.active_debts(db):
            currency = db.query(Currency).filter_by(id=d.currency_id).first()
            member = db.query(Member).filter_by(id=d.member_id).first()
            debt_rows.append([
                d.id,
                member.get_display_name() if member else d.member_id,
                currency.code if currency else d.currency_id,
                d.remaining / (10 ** (currency.decimal_places if currency else 2)),
                d.description or "",
            ])

        contrib_rows = []
        for ob in db.query(ContributionObligation).all():
            req = db.query(ContributionRequest).filter_by(id=ob.contribution_request_id).first()
            member = db.query(Member).filter_by(id=ob.member_id).first()
            currency = db.query(Currency).filter_by(id=req.currency_id).first() if req else None
            scale = 10 ** (currency.decimal_places if currency else 2)
            contrib_rows.append([
                ob.contribution_request_id,
                member.get_display_name() if member else ob.member_id,
                currency.code if currency else "",
                ob.amount / scale,
                ob.paid_amount / scale,
                (ob.amount - ob.paid_amount) / scale,
                ob.status,
            ])

        return export_sheets(title, [
            {"title": "الصندوق", "headers": ["العملة", "الرصيد"], "rows": cash_rows},
            {
                "title": "العمليات",
                "headers": ["المعرف", "التاريخ", "النوع", "العملة", "المبلغ", "العضو", "الوصف", "الحالة"],
                "rows": tx_rows,
            },
            {
                "title": "الديون",
                "headers": ["المعرف", "العضو", "العملة", "المتبقي", "الوصف"],
                "rows": debt_rows,
            },
            {
                "title": "المساهمات",
                "headers": ["طلب", "العضو", "العملة", "المطلوب", "المدفوع", "المتبقي", "الحالة"],
                "rows": contrib_rows,
            },
        ])

    @staticmethod
    def period_bounds(kind: str) -> Tuple[datetime, datetime]:
        now = datetime.utcnow()
        if kind == "weekly":
            # last 7 days
            return now - timedelta(days=7), now
        if kind == "monthly":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return start, now
        return now - timedelta(days=30), now
