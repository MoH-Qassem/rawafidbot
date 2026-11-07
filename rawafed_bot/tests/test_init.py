"""Initialization & Seed tests for Phase 1."""
import pytest
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.database.models import (
    Member, Currency, Account, ExpenseCategory, BotSetting
)


class TestSeeding:
    def test_seed_currencies(self, db):
        seed_all(db)
        currencies = db.query(Currency).all()
        codes = {c.code for c in currencies}
        assert "USD" in codes
        assert "SYP" in codes
        assert "TRY" in codes
        usd = db.query(Currency).filter_by(code="USD").first()
        assert usd.name_ar == "دولار أمريكي"
        assert "$" in usd.aliases

    def test_seed_members(self, db):
        seed_all(db)
        members = db.query(Member).all()
        assert len(members) == 5
        from rawafed_bot.core.config import settings
        ceo = db.query(Member).filter_by(telegram_id=settings.CEO_TELEGRAM_ID).first()
        assert ceo is not None
        assert ceo.is_ceo is True

    def test_seed_accounts(self, db):
        seed_all(db)
        accounts = db.query(Account).all()
        currencies = db.query(Currency).all()
        members = db.query(Member).all()
        # Cash box accounts per currency
        cash_boxes = [a for a in accounts if a.account_type == "cash_box"]
        assert len(cash_boxes) == len(currencies)
        for cb in cash_boxes:
            assert cb.balance == 0
        # Member accounts per currency
        member_types = ["member_equity", "member_due", "advance_pending"]
        for m in members:
            for c in currencies:
                for mt in member_types:
                    acct = db.query(Account).filter_by(
                        member_id=m.id, currency_id=c.id, account_type=mt
                    ).first()
                    assert acct is not None, f"Missing {mt} for member {m.id} currency {c.id}"
                    assert acct.balance == 0

    def test_seed_expense_categories(self, db):
        seed_all(db)
        cats = db.query(ExpenseCategory).all()
        names = {c.name for c in cats}
        assert "مواصلات" in names
        assert "أخرى" in names

    def test_seed_settings(self, db):
        seed_all(db)
        tz = db.query(BotSetting).filter_by(key="timezone").first()
        assert tz is not None
        assert tz.value == "Asia/Damascus"


class TestDatabaseIntegrity:
    def test_transaction_types_enum(self, db):
        # Ensure model fields exist without runtime enum strictness issues
        from rawafed_bot.database.models.transaction import TransactionType
        assert TransactionType.DEPOSIT.value == "deposit"
        assert TransactionType.EXPENSE.value == "expense"

    def test_cash_box_no_negative_balance_constraint_not_enforced_in_model(self):
        # This is a business rule tested later; model does not enforce at DB level
        pass

    def test_accounts_balance_type_is_integer(self):
        from rawafed_bot.database.models.account import Account
        from sqlalchemy import BigInteger
        assert isinstance(Account.balance.type, BigInteger)
