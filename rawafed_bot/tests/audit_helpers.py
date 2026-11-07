"""Helpers for financial audit tests (minor-unit amounts)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from rawafed_bot.database.models.account import Account
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.member import Member
from rawafed_bot.utils.money import to_minor_units


def currency_by_code(db: Session, code: str) -> Currency:
    return db.query(Currency).filter_by(code=code).one()


def cash(db: Session, code: str) -> Account:
    cur = currency_by_code(db, code)
    return db.query(Account).filter_by(account_type="cash_box", currency_id=cur.id).one()


def expense_acc(db: Session, code: str) -> Account:
    cur = currency_by_code(db, code)
    return db.query(Account).filter_by(account_type="expense_summary", currency_id=cur.id).one()


def members(db: Session) -> list[Member]:
    return db.query(Member).order_by(Member.id).all()


def m(amount: str | int | float, code: str, db: Session) -> int:
    """Human amount → minor units for currency code (supports negative)."""
    cur = currency_by_code(db, code)
    from decimal import Decimal
    from rawafed_bot.utils.money import normalize_amount_text

    if isinstance(amount, str):
        value = Decimal(normalize_amount_text(amount))
    else:
        value = Decimal(str(amount))
    sign = -1 if value < 0 else 1
    return sign * to_minor_units(abs(value), cur.decimal_places)


def cat_id(db: Session) -> int:
    from rawafed_bot.database.models.expense_category import ExpenseCategory
    return db.query(ExpenseCategory).first().id
