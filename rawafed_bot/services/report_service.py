"""Report facade used by bot handlers."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.expense_category import ExpenseCategory
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.transaction import Transaction
from rawafed_bot.reports.generator import ReportGenerator, TYPE_LABELS
from rawafed_bot.services.query_service import QueryService
from rawafed_bot.utils.money import format_amount


class ReportService:
    @staticmethod
    def cash_box_report(db: Session) -> str:
        return ReportGenerator.cash_box_text(db)

    @staticmethod
    def full_summary(db: Session, date_from: datetime = None, date_to: datetime = None) -> str:
        return ReportGenerator.full_summary_text(db, date_from, date_to)

    @staticmethod
    def expenses_by_category(db: Session) -> str:
        lines = ["📉 المصروفات حسب التصنيف", "────────────"]
        currencies = QueryService.get_currencies(db)
        any_row = False
        for cur in currencies:
            rows = QueryService.expense_totals_by_category(db, currency_id=cur.id)
            if not rows:
                continue
            any_row = True
            lines.append(f"\n{cur.code}:")
            for r in rows:
                lines.append(f"- {r['category_name']}: {format_amount(r['amount'], cur)}")
        if not any_row:
            lines.append("لا توجد مصروفات مسجّلة.")
        # Also show ledger expense balances
        lines.append("\nإجمالي حساب المصروفات:")
        for row in QueryService.expense_summary_balances(db):
            lines.append(format_amount(row["balance"], row["currency"]))
        return "\n".join(lines)

    @staticmethod
    def member_accounts(db: Session) -> str:
        lines = ["👥 حسابات الأعضاء", "────────────"]
        for member in db.query(Member).filter_by(is_active=True).order_by(Member.id).all():
            lines.append(ReportGenerator.member_statement_text(db, member.id))
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def history(db: Session, limit: int = 20) -> str:
        lines = ["📚 سجل العمليات", "────────────"]
        txs = QueryService.transactions(db, limit=limit)
        if not txs:
            lines.append("لا توجد عمليات.")
            return "\n".join(lines)
        for tx in txs:
            currency = db.query(Currency).filter_by(id=tx.currency_id).first()
            member = db.query(Member).filter_by(id=tx.member_id).first()
            typ = TYPE_LABELS.get(tx.transaction_type, tx.transaction_type)
            when = tx.created_at.strftime("%Y-%m-%d %H:%M") if tx.created_at else ""
            lines.append(
                f"#{tx.id} | {when}\n"
                f"{typ} — {format_amount(tx.amount, currency)}\n"
                f"{member.get_display_name() if member else tx.member_id} | {tx.status}\n"
                f"{tx.description or '-'}\n"
            )
        return "\n".join(lines)

    @staticmethod
    def debts_report(db: Session) -> str:
        lines = ["📋 الديون والمستحقات", "────────────"]
        debts = QueryService.active_debts(db)
        if not debts:
            lines.append("لا توجد ديون نشطة.")
            return "\n".join(lines)
        for d in debts:
            member = db.query(Member).filter_by(id=d.member_id).first()
            currency = db.query(Currency).filter_by(id=d.currency_id).first()
            lines.append(
                f"#{d.id} — {member.get_display_name() if member else d.member_id}\n"
                f"المتبقي: {format_amount(d.remaining, currency)}\n"
                f"{d.description or '-'}\n"
            )
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
