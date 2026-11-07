"""Tests for the Double-Entry Accounting Engine."""
import pytest
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.database.models import Account
from rawafed_bot.accounting.engine import AccountingEngine, JournalLineData, AccountingError


class TestAccountingEngine:
    def test_create_balanced_entry(self, db):
        seed_all(db)
        usd = db.query(Account).filter_by(account_type="cash_box").first()
        rev = db.query(Account).filter_by(account_type="revenue").first()
        lines = [
            JournalLineData(usd.id, debit=1000, credit=0),
            JournalLineData(rev.id, debit=0, credit=1000),
        ]
        entry = AccountingEngine.create_journal_entry(
            db=db, currency_id=usd.currency_id, description="test", created_by=1, lines=lines
        )
        db.commit()
        assert entry is not None
        assert entry.entry_number.startswith("JE-")
        db.refresh(usd)
        db.refresh(rev)
        assert usd.balance == 1000
        assert rev.balance == -1000

    def test_unbalanced_entry_rejected(self, db):
        seed_all(db)
        usd = db.query(Account).filter_by(account_type="cash_box").first()
        rev = db.query(Account).filter_by(account_type="revenue").first()
        lines = [
            JournalLineData(usd.id, debit=1000, credit=0),
            JournalLineData(rev.id, debit=0, credit=500),
        ]
        with pytest.raises(AccountingError) as exc:
            AccountingEngine.create_journal_entry(
                db=db, currency_id=usd.currency_id, description="bad", created_by=1, lines=lines
            )
        assert "غير متوازن" in str(exc.value)

    def test_zero_amount_entry_rejected(self, db):
        seed_all(db)
        usd = db.query(Account).filter_by(account_type="cash_box").first()
        rev = db.query(Account).filter_by(account_type="revenue").first()
        lines = [
            JournalLineData(usd.id, debit=0, credit=0),
            JournalLineData(rev.id, debit=0, credit=0),
        ]
        with pytest.raises(AccountingError):
            AccountingEngine.create_journal_entry(
                db=db, currency_id=usd.currency_id, description="zero", created_by=1, lines=lines
            )

    def test_duplicate_account_rejected(self, db):
        seed_all(db)
        usd = db.query(Account).filter_by(account_type="cash_box").first()
        lines = [
            JournalLineData(usd.id, debit=500, credit=0),
            JournalLineData(usd.id, debit=0, credit=500),
        ]
        with pytest.raises(AccountingError) as exc:
            AccountingEngine.create_journal_entry(
                db=db, currency_id=usd.currency_id, description="dup-acc", created_by=1, lines=lines
            )
        assert "نفس الحساب" in str(exc.value)

    def test_mixed_currency_rejected(self, db):
        seed_all(db)
        cash_usd = db.query(Account).filter_by(account_type="cash_box").join(Account.currency).filter_by(code="USD").first()
        cash_syp = db.query(Account).filter_by(account_type="cash_box").join(Account.currency).filter_by(code="SYP").first()
        lines = [
            JournalLineData(cash_usd.id, debit=100, credit=0),
            JournalLineData(cash_syp.id, debit=0, credit=100),
        ]
        with pytest.raises(AccountingError) as exc:
            AccountingEngine.create_journal_entry(
                db=db, currency_id=cash_usd.currency_id, description="mix", created_by=1, lines=lines
            )
        assert "اختلاف العملات" in str(exc.value)

    def test_cash_box_negative_allowed(self, db):
        seed_all(db)
        usd = db.query(Account).filter_by(account_type="cash_box").first()
        rev = db.query(Account).filter_by(account_type="revenue").first()
        lines = [
            JournalLineData(usd.id, debit=0, credit=100),
            JournalLineData(rev.id, debit=100, credit=0),
        ]
        AccountingEngine.create_journal_entry(
            db=db, currency_id=usd.currency_id, description="neg", created_by=1, lines=lines
        )
        db.commit()
        db.refresh(usd)
        assert usd.balance == -100

    def test_idempotency_prevents_duplicate(self, db):
        seed_all(db)
        usd = db.query(Account).filter_by(account_type="cash_box").first()
        rev = db.query(Account).filter_by(account_type="revenue").first()
        key = "test-idem-123"
        lines = [
            JournalLineData(usd.id, debit=100, credit=0),
            JournalLineData(rev.id, debit=0, credit=100),
        ]
        AccountingEngine.create_journal_entry(
            db=db, currency_id=usd.currency_id, description="first", created_by=1,
            lines=lines, idempotency_key=key,
        )
        db.commit()
        db.rollback()
        lines2 = [
            JournalLineData(usd.id, debit=200, credit=0),
            JournalLineData(rev.id, debit=0, credit=200),
        ]
        with pytest.raises(AccountingError) as exc:
            AccountingEngine.create_journal_entry(
                db=db, currency_id=usd.currency_id, description="dup", created_by=1,
                lines=lines2, idempotency_key=key,
            )
        assert "تم تسجيلها" in str(exc.value)

    def test_reverse_entry_creates_opposite(self, db):
        seed_all(db)
        usd = db.query(Account).filter_by(account_type="cash_box").first()
        rev = db.query(Account).filter_by(account_type="revenue").first()
        lines = [
            JournalLineData(usd.id, debit=500, credit=0),
            JournalLineData(rev.id, debit=0, credit=500),
        ]
        entry = AccountingEngine.create_journal_entry(
            db=db, currency_id=usd.currency_id, description="orig", created_by=1, lines=lines
        )
        db.commit()
        db.refresh(usd)
        db.refresh(rev)
        assert usd.balance == 500
        assert rev.balance == -500

        reversal = AccountingEngine.reverse_journal_entry(
            db=db, journal_entry_id=entry.id, reason="test reversal", created_by=1,
        )
        db.commit()
        db.refresh(usd)
        db.refresh(rev)
        assert usd.balance == 0
        assert rev.balance == 0
        assert reversal.description.startswith("عكس")

    def test_currency_isolation(self, db):
        seed_all(db)
        usd = db.query(Account).filter_by(account_type="cash_box").join(Account.currency).filter_by(code="USD").first()
        syp = db.query(Account).filter_by(account_type="cash_box").join(Account.currency).filter_by(code="SYP").first()
        rev_usd = db.query(Account).filter_by(account_type="revenue").join(Account.currency).filter_by(code="USD").first()
        lines = [
            JournalLineData(usd.id, debit=1000, credit=0),
            JournalLineData(rev_usd.id, debit=0, credit=1000),
        ]
        AccountingEngine.create_journal_entry(
            db=db, currency_id=usd.currency_id, description="usd only", created_by=1, lines=lines
        )
        db.commit()
        db.refresh(syp)
        db.refresh(usd)
        assert syp.balance == 0
        assert usd.balance == 1000
