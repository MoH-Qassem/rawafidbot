"""Seed an explicit member→company debt for repayment tests."""
from __future__ import annotations

from rawafed_bot.database.models.debt import MemberDebt
from rawafed_bot.database.models.transaction import Transaction, TransactionType


def seed_member_debt(db, member_id: int, currency_id: int, amount: int, key: str) -> MemberDebt:
    tx = Transaction(
        transaction_type=TransactionType.EXPENSE.value,
        amount=amount,
        currency_id=currency_id,
        member_id=member_id,
        description="seed debt",
        created_by=member_id,
        idempotency_key=key,
    )
    db.add(tx)
    db.flush()
    debt = MemberDebt(
        member_id=member_id,
        currency_id=currency_id,
        amount=amount,
        remaining=amount,
        description="seed debt",
        transaction_id=tx.id,
        status="active",
    )
    db.add(debt)
    db.commit()
    db.refresh(debt)
    return debt
