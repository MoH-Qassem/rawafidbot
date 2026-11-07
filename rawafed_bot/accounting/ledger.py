"""Ledger integrity helpers: recompute balances from journal lines."""
from __future__ import annotations

from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from rawafed_bot.database.models.account import Account
from rawafed_bot.database.models.journal import JournalEntry, JournalLine


def assert_all_entries_balanced(db: Session) -> int:
    """Raise AssertionError if any journal entry is unbalanced. Returns entry count."""
    entries = db.query(JournalEntry).all()
    for entry in entries:
        lines = db.query(JournalLine).filter_by(journal_entry_id=entry.id).all()
        debit = sum(l.debit for l in lines)
        credit = sum(l.credit for l in lines)
        if debit != credit:
            raise AssertionError(
                f"Unbalanced entry {entry.entry_number}: debit={debit} credit={credit}"
            )
        currencies = set()
        for line in lines:
            acc = db.query(Account).filter_by(id=line.account_id).first()
            currencies.add(acc.currency_id if acc else None)
        if len(currencies) != 1 or entry.currency_id not in currencies:
            raise AssertionError(f"Currency mix in entry {entry.entry_number}")
    return len(entries)


def recompute_balances_from_journal(db: Session) -> Dict[int, int]:
    """Return {account_id: balance} from sum(debit - credit) across all lines."""
    balances: Dict[int, int] = {}
    lines = db.query(JournalLine).all()
    for line in lines:
        balances[line.account_id] = balances.get(line.account_id, 0) + line.debit - line.credit
    return balances


def assert_stored_balances_match_ledger(db: Session) -> None:
    """Compare Account.balance with recomputed journal totals."""
    computed = recompute_balances_from_journal(db)
    accounts = db.query(Account).all()
    for acc in accounts:
        expected = computed.get(acc.id, 0)
        if acc.balance != expected:
            raise AssertionError(
                f"Account {acc.id} ({acc.account_type}/{acc.currency_id}) "
                f"stored={acc.balance} ledger={expected}"
            )
    # No orphan ledger lines with missing accounts
    for aid in computed:
        if not any(a.id == aid for a in accounts):
            raise AssertionError(f"Orphan journal lines for account_id={aid}")


def cash_box_balance(db: Session, currency_id: int) -> int:
    acc = db.query(Account).filter_by(account_type="cash_box", currency_id=currency_id).first()
    return acc.balance if acc else 0


def expense_balance(db: Session, currency_id: int) -> int:
    acc = db.query(Account).filter_by(account_type="expense_summary", currency_id=currency_id).first()
    return acc.balance if acc else 0
