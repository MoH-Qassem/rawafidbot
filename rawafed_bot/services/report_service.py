"""Report facade used by bot handlers."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.member import Member
from rawafed_bot.reports.generator import ReportGenerator, TYPE_LABELS
from rawafed_bot.services.query_service import QueryService
from rawafed_bot.utils.money import format_amount

_STATUS_AR = {
    "active": "نشط",
    "reversed": "ملغى",
    "repaid": "مسدد",
    "open": "مفتوح",
    "closed": "مغلق",
}


def _sep() -> str:
    return "━━━━━━━━━━━━━━━━"


class ReportService:
    @staticmethod
    def cash_box_report(db: Session) -> str:
        return ReportGenerator.cash_box_text(db)

    @staticmethod
    def full_summary(db: Session, date_from: datetime = None, date_to: datetime = None) -> str:
        return ReportGenerator.full_summary_text(db, date_from, date_to)

    @staticmethod
    def expenses_by_category(db: Session) -> str:
        lines = ["📉 المصروفات حسب التصنيف", _sep()]
        currencies = QueryService.get_currencies(db)
        any_row = False
        for cur in currencies:
            rows = QueryService.expense_totals_by_category(db, currency_id=cur.id)
            if not rows:
                continue
            any_row = True
            lines.append(f"\n• {cur.code}")
            for r in rows:
                lines.append(f"  – {r['category_name']}: {format_amount(r['amount'], cur)}")
        if not any_row:
            lines.append("لا توجد مصروفات مسجّلة.")
        lines.append("")
        lines.append("إجمالي حساب المصروفات:")
        for row in QueryService.expense_summary_balances(db):
            lines.append(f"  • {format_amount(row['balance'], row['currency'])}")
        return "\n".join(lines)

    @staticmethod
    def member_accounts(db: Session) -> str:
        lines = ["👥 حسابات الأعضاء", _sep()]
        for member in db.query(Member).filter_by(is_active=True).order_by(Member.id).all():
            lines.append(ReportGenerator.member_statement_text(db, member.id))
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def history(db: Session, limit: int = 20) -> str:
        lines = ["📒 سجل العمليات", _sep()]
        txs = QueryService.transactions(db, limit=limit)
        if not txs:
            lines.append("لا توجد عمليات بعد.")
            return "\n".join(lines)

        for i, tx in enumerate(txs):
            currency = db.query(Currency).filter_by(id=tx.currency_id).first()
            member = db.query(Member).filter_by(id=tx.member_id).first()
            typ = TYPE_LABELS.get(tx.transaction_type, tx.transaction_type)
            when = tx.created_at.strftime("%Y-%m-%d  %H:%M") if tx.created_at else "—"
            status = _STATUS_AR.get(tx.status, tx.status or "—")
            who = member.get_display_name() if member else str(tx.member_id)
            amount = format_amount(tx.amount, currency) if currency else str(tx.amount)
            desc = (tx.description or "—").strip()
            if len(desc) > 120:
                desc = desc[:117] + "…"

            block = [
                f"#{tx.id}  ·  {typ}",
                f"💰  {amount}",
                f"👤  {who}",
                f"📅  {when}",
                f"📌  {status}",
                f"📝  {desc}",
            ]
            lines.append("\n".join(block))
            if i < len(txs) - 1:
                lines.append(_sep())

        lines.append(_sep())
        lines.append(f"عرض آخر {len(txs)} عملية")
        return "\n".join(lines)

    @staticmethod
    def debts_report(db: Session) -> str:
        lines = ["📋 الديون على الأعضاء (لصالح الصندوق)", _sep()]
        debts = QueryService.active_debts(db)
        if not debts:
            lines.append("لا توجد ديون نشطة.")
            return "\n".join(lines)
        for i, d in enumerate(debts):
            member = db.query(Member).filter_by(id=d.member_id).first()
            currency = db.query(Currency).filter_by(id=d.currency_id).first()
            who = member.get_display_name() if member else str(d.member_id)
            block = [
                f"#{d.id}  ·  {who}",
                f"💰 المتبقي: {format_amount(d.remaining, currency)}",
                f"📝 {(d.description or '—').strip()}",
            ]
            lines.append("\n".join(block))
            if i < len(debts) - 1:
                lines.append(_sep())
        return "\n".join(lines)

    @staticmethod
    def weekly_report(db: Session) -> tuple[str, object]:
        date_from, date_to = ReportGenerator.period_bounds("weekly")
        text = ReportGenerator.full_summary_text(db, date_from, date_to)
        path = ReportGenerator.export_period_excel(db, date_from, date_to, title="تقرير_أسبوعي")
        return text, path

    @staticmethod
    def monthly_report(db: Session) -> tuple[str, object]:
        date_from, date_to = ReportGenerator.period_bounds("monthly")
        text = ReportGenerator.full_summary_text(db, date_from, date_to)
        path = ReportGenerator.export_period_excel(db, date_from, date_to, title="تقرير_شهري")
        return text, path

    @staticmethod
    def export_excel(db: Session, title: str = "تقرير_مالي"):
        return ReportGenerator.export_period_excel(db, title=title)
