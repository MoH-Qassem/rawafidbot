"""Read-only financial queries for UI and reports."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from rawafed_bot.database.models.account import Account
from rawafed_bot.database.models.advance import Advance
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.debt import MemberDebt
from rawafed_bot.database.models.expense_category import ExpenseCategory
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.transaction import Transaction


class QueryService:
    @staticmethod
    def cash_box_balances(db: Session) -> List[dict]:
        rows = []
        accounts = db.query(Account).filter_by(account_type="cash_box").all()
        for acc in accounts:
            currency = db.query(Currency).filter_by(id=acc.currency_id).first()
            rows.append({
                "currency_id": acc.currency_id,
                "currency": currency,
                "balance": acc.balance,
                "account_id": acc.id,
            })
        return rows

    @staticmethod
    def expense_totals_by_category(
        db: Session, currency_id: int = None, date_from: datetime = None, date_to: datetime = None,
    ) -> List[dict]:
        q = db.query(Transaction).filter(
            Transaction.transaction_type.in_(["expense", "personal_expense", "advance_settlement"]),
            Transaction.status == "active",
        )
        if currency_id:
            q = q.filter(Transaction.currency_id == currency_id)
        if date_from:
            q = q.filter(Transaction.created_at >= date_from)
        if date_to:
            q = q.filter(Transaction.created_at <= date_to)
        totals: Dict[int, int] = {}
        for tx in q.all():
            if tx.transaction_type == "advance_settlement" and (tx.amount or 0) <= 0:
                continue
            cat_id = tx.category_id or 0
            totals[cat_id] = totals.get(cat_id, 0) + tx.amount
        result = []
        for cat_id, amount in totals.items():
            if cat_id:
                cat = db.query(ExpenseCategory).filter_by(id=cat_id).first()
                name = cat.name if cat else f"#{cat_id}"
            else:
                name = "غير مصنف"
            result.append({"category_id": cat_id, "category_name": name, "amount": amount})
        return sorted(result, key=lambda x: x["amount"], reverse=True)

    @staticmethod
    def transactions(
        db: Session,
        currency_id: int = None,
        member_id: int = None,
        tx_type: str = None,
        date_from: datetime = None,
        date_to: datetime = None,
        limit: int = 50,
    ) -> List[Transaction]:
        q = db.query(Transaction).order_by(Transaction.created_at.desc())
        if currency_id:
            q = q.filter(Transaction.currency_id == currency_id)
        if member_id:
            q = q.filter(Transaction.member_id == member_id)
        if tx_type:
            q = q.filter(Transaction.transaction_type == tx_type)
        if date_from:
            q = q.filter(Transaction.created_at >= date_from)
        if date_to:
            q = q.filter(Transaction.created_at <= date_to)
        return q.limit(limit).all()

    @staticmethod
    def active_debts(db: Session, member_id: int = None) -> List[MemberDebt]:
        q = db.query(MemberDebt).filter(MemberDebt.status == "active", MemberDebt.remaining > 0)
        if member_id:
            q = q.filter(MemberDebt.member_id == member_id)
        return q.order_by(MemberDebt.created_at.desc()).all()

    @staticmethod
    def open_advances(db: Session, member_id: int = None) -> List[Advance]:
        q = db.query(Advance).filter(Advance.status.in_(["open", "partially_settled"]))
        if member_id:
            q = q.filter(Advance.member_id == member_id)
        return q.order_by(Advance.created_at.desc()).all()

    @staticmethod
    def member_statement(db: Session, member_id: int) -> dict:
        member = db.query(Member).filter_by(id=member_id).first()
        accounts = db.query(Account).filter(
            Account.member_id == member_id,
            Account.account_type.in_(["member_equity", "member_due", "advance_pending"]),
        ).all()
        by_currency: Dict[int, dict] = {}
        for acc in accounts:
            slot = by_currency.setdefault(acc.currency_id, {
                "currency_id": acc.currency_id,
                "equity": 0,
                "due": 0,
                "advance": 0,
            })
            if acc.account_type == "member_equity":
                slot["equity"] = acc.balance
            elif acc.account_type == "member_due":
                slot["due"] = acc.balance
            elif acc.account_type == "advance_pending":
                slot["advance"] = acc.balance
        if by_currency:
            currencies = {
                c.id: c for c in db.query(Currency).filter(
                    Currency.id.in_(list(by_currency.keys()))
                ).all()
            }
        else:
            currencies = {}
        rows = []
        for cid, slot in by_currency.items():
            slot["currency"] = currencies.get(cid)
            rows.append(slot)
        return {"member": member, "balances": rows}

    @staticmethod
    def expense_summary_balances(db: Session) -> List[dict]:
        rows = []
        for acc in db.query(Account).filter_by(account_type="expense_summary").all():
            currency = db.query(Currency).filter_by(id=acc.currency_id).first()
            rows.append({"currency": currency, "balance": acc.balance, "currency_id": acc.currency_id})
        return rows

    @staticmethod
    def get_categories(db: Session) -> List[ExpenseCategory]:
        return db.query(ExpenseCategory).filter_by(is_active=True).order_by(ExpenseCategory.id).all()

    @staticmethod
    def get_currencies(db: Session) -> List[Currency]:
        return db.query(Currency).filter_by(is_active=True).order_by(Currency.id).all()
