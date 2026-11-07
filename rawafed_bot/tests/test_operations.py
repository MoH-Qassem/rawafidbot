"""Tests for individual financial operations."""
import pytest
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.database.models import Account, MemberDebt, Advance, Transaction
from rawafed_bot.services.operation_service import OperationService, OperationError

class TestOperations:
    def test_deposit_increases_cash_box(self, db):
        seed_all(db)
        member = db.query(Account).filter_by(account_type="member_equity").first().member
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        cash_box = db.query(Account).filter_by(account_type="cash_box", currency_id=currency_id).first()
        OperationService.record_deposit(
            db=db, amount=1000, currency_id=currency_id, member_id=member.id,
            description="test", created_by=member.id,
        )
        db.refresh(cash_box)
        assert cash_box.balance == 1000

    def test_expense_from_box_decreases_cash_box(self, db):
        seed_all(db)
        member = db.query(Account).filter_by(account_type="member_equity").first().member
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        cash_box = db.query(Account).filter_by(account_type="cash_box", currency_id=currency_id).first()
        OperationService.record_deposit(
            db=db, amount=1000, currency_id=currency_id, member_id=member.id,
            description="dep", created_by=member.id,
        )
        OperationService.record_expense_from_box(
            db=db, amount=200, currency_id=currency_id, category_id=1,
            member_id=member.id, description="exp", created_by=member.id,
        )
        db.refresh(cash_box)
        assert cash_box.balance == 800

    def test_personal_expense_hits_cash_and_creates_debt(self, db):
        seed_all(db)
        member = db.query(Account).filter_by(account_type="member_equity").first().member
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        cash_box = db.query(Account).filter_by(account_type="cash_box", currency_id=currency_id).first()
        OperationService.record_deposit(
            db=db, amount=100, currency_id=currency_id, member_id=member.id,
            description="dep", created_by=member.id,
        )
        tx = OperationService.record_personal_expense(
            db=db, amount=50, currency_id=currency_id, category_id=1,
            member_id=member.id, description="personal", created_by=member.id,
        )
        db.refresh(cash_box)
        assert cash_box.balance == 50
        debt = db.query(MemberDebt).filter_by(transaction_id=tx.id).first()
        assert debt is not None
        assert debt.remaining == 50

    def test_personal_expense_allows_negative_cash(self, db):
        seed_all(db)
        member = db.query(Account).filter_by(account_type="member_equity").first().member
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        cash_box = db.query(Account).filter_by(account_type="cash_box", currency_id=currency_id).first()
        OperationService.record_personal_expense(
            db=db, amount=75, currency_id=currency_id, category_id=1,
            member_id=member.id, description="over", created_by=member.id,
        )
        db.refresh(cash_box)
        assert cash_box.balance == -75

    def test_debt_repayment_reduces_debt_and_restores_cash(self, db):
        seed_all(db)
        member = db.query(Account).filter_by(account_type="member_equity").first().member
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        cash_box = db.query(Account).filter_by(account_type="cash_box", currency_id=currency_id).first()
        OperationService.record_deposit(
            db=db, amount=1000, currency_id=currency_id, member_id=member.id,
            description="dep", created_by=member.id,
        )
        tx = OperationService.record_personal_expense(
            db=db, amount=50, currency_id=currency_id, category_id=1,
            member_id=member.id, description="personal", created_by=member.id,
        )
        debt = db.query(MemberDebt).filter_by(transaction_id=tx.id).first()
        OperationService.record_debt_repayment(
            db=db, amount=20, currency_id=currency_id, member_id=member.id,
            description="repay", created_by=member.id, debt_id=debt.id,
        )
        db.refresh(debt)
        db.refresh(cash_box)
        assert debt.remaining == 30
        assert cash_box.balance == 970

    def test_advance_withdrawal_not_expense(self, db):
        seed_all(db)
        member = db.query(Account).filter_by(account_type="member_equity").first().member
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        cash_box = db.query(Account).filter_by(account_type="cash_box", currency_id=currency_id).first()
        OperationService.record_deposit(
            db=db, amount=500, currency_id=currency_id, member_id=member.id,
            description="dep", created_by=member.id,
        )
        tx, advance = OperationService.record_withdrawal_as_advance(
            db=db, amount=200, currency_id=currency_id, member_id=member.id,
            description="withdraw", purpose="work", created_by=member.id,
        )
        db.refresh(cash_box)
        assert cash_box.balance == 300
        assert advance.status == "open"
        expense_count = db.query(Transaction).filter_by(
            transaction_type="expense", member_id=member.id
        ).count()
        assert expense_count == 0

    def test_advance_settlement_balanced(self, db):
        seed_all(db)
        member = db.query(Account).filter_by(account_type="member_equity").first().member
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        cash_box = db.query(Account).filter_by(account_type="cash_box", currency_id=currency_id).first()
        OperationService.record_deposit(
            db=db, amount=500, currency_id=currency_id, member_id=member.id,
            description="dep", created_by=member.id,
        )
        tx, advance = OperationService.record_withdrawal_as_advance(
            db=db, amount=200, currency_id=currency_id, member_id=member.id,
            description="withdraw", purpose="work", created_by=member.id,
        )
        tx2, settlement = OperationService.settle_advance(
            db=db, advance_id=advance.id, expense_amount=150,
            returned_amount=50, description="settle", created_by=member.id,
        )
        db.refresh(cash_box)
        db.refresh(advance)
        assert cash_box.balance == 500 - 200 + 50
        assert advance.status == "fully_settled"
        assert settlement.expense_amount == 150
        assert settlement.returned_amount == 50
        assert settlement.additional_amount == 0

    def test_advance_settlement_exceeds_rejected(self, db):
        seed_all(db)
        member = db.query(Account).filter_by(account_type="member_equity").first().member
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        OperationService.record_deposit(
            db=db, amount=500, currency_id=currency_id, member_id=member.id,
            description="dep", created_by=member.id,
        )
        tx, advance = OperationService.record_withdrawal_as_advance(
            db=db, amount=200, currency_id=currency_id, member_id=member.id,
            description="withdraw", purpose="work", created_by=member.id,
        )
        with pytest.raises(OperationError) as exc:
            OperationService.settle_advance(
                db=db, advance_id=advance.id, expense_amount=150,
                returned_amount=100, description="settle", created_by=member.id,
            )
        assert "يتجاوز" in str(exc.value)

    def test_rollback_on_failure(self, db):
        seed_all(db)
        member = db.query(Account).filter_by(account_type="member_equity").first().member
        currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        tx_count_before = db.query(Transaction).count()
        with pytest.raises(Exception):
            OperationService.record_expense_from_box(
                db=db, amount=0, currency_id=currency_id, category_id=1,
                member_id=member.id, description="exp", created_by=member.id,
            )
        tx_count_after = db.query(Transaction).count()
        assert tx_count_after == tx_count_before
