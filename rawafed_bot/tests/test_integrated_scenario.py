"""Integrated scenario test for the accounting engine.

Scenario:
- Deposit 1000 USD
- Expense 100 USD from box
- Personal expense 50 USD
- Debt repayment 20 USD
- Advance withdrawal 200 USD
- Advance settlement: 150 expense + 50 returned

Expected:
- Cash box: 730
- Total expenses: 300
- Remaining debt: 30
- Advance: fully settled
- No duplicate expenses
- All journal entries balanced
"""
import pytest
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.database.models import Account, MemberDebt, Advance, JournalEntry, JournalLine
from rawafed_bot.services.operation_service import OperationService


class TestIntegratedScenario:
    def test_full_scenario(self, db):
        seed_all(db)
        # Get first member as member1, second as member2
        members = db.query(Account).filter_by(account_type="member_equity").all()
        member1 = members[0].member
        member2 = members[1].member
        usd_currency_id = db.query(Account).filter_by(account_type="cash_box").first().currency_id
        cash_box = db.query(Account).filter_by(account_type="cash_box", currency_id=usd_currency_id).first()
        expense_acc = db.query(Account).filter_by(account_type="expense_summary", currency_id=usd_currency_id).first()

        # 1. Deposit 1000 USD
        OperationService.record_deposit(
            db=db, amount=1000, currency_id=usd_currency_id, member_id=member1.id,
            description="إيداع أولي", created_by=member1.id,
        )
        db.refresh(cash_box)
        assert cash_box.balance == 1000

        # 2. Expense 100 USD from box
        OperationService.record_expense_from_box(
            db=db, amount=100, currency_id=usd_currency_id, category_id=1,
            member_id=member1.id, description="مصروف مكتبي", created_by=member1.id,
        )
        db.refresh(cash_box)
        db.refresh(expense_acc)
        assert cash_box.balance == 900
        assert expense_acc.balance == 100

        # 3. Personal expense 50 USD by member1
        tx_personal = OperationService.record_personal_expense(
            db=db, amount=50, currency_id=usd_currency_id, category_id=1,
            member_id=member1.id, description="مصروف شخصي", created_by=member1.id,
        )
        db.refresh(cash_box)
        db.refresh(expense_acc)
        assert cash_box.balance == 900  # unchanged
        assert expense_acc.balance == 150
        debt = db.query(MemberDebt).filter_by(transaction_id=tx_personal.id).first()
        assert debt.remaining == 50

        # 4. Debt repayment 20 USD
        OperationService.record_debt_repayment(
            db=db, amount=20, currency_id=usd_currency_id, member_id=member1.id,
            description="تسديد جزئي", created_by=member1.id, debt_id=debt.id,
        )
        db.refresh(cash_box)
        db.refresh(debt)
        assert cash_box.balance == 880
        assert debt.remaining == 30

        # 5. Advance withdrawal 200 USD to member2
        tx_adv, advance = OperationService.record_withdrawal_as_advance(
            db=db, amount=200, currency_id=usd_currency_id, member_id=member2.id,
            description="سحب عهدة", purpose="سفر", created_by=member2.id,
        )
        db.refresh(cash_box)
        assert cash_box.balance == 680
        assert advance.status == "open"

        # 6. Settle advance: 150 expense + 50 returned
        tx_settle, settlement = OperationService.settle_advance(
            db=db, advance_id=advance.id, expense_amount=150,
            returned_amount=50, description="تسوية العهدة", created_by=member2.id,
        )
        db.refresh(cash_box)
        db.refresh(expense_acc)
        db.refresh(advance)
        assert cash_box.balance == 730
        assert expense_acc.balance == 300
        assert advance.status == "fully_settled"
        assert settlement.additional_amount == 0

        # Verify all journal entries are balanced
        entries = db.query(JournalEntry).all()
        for entry in entries:
            lines = db.query(JournalLine).filter_by(journal_entry_id=entry.id).all()
            total_debit = sum(line.debit for line in lines)
            total_credit = sum(line.credit for line in lines)
            assert total_debit == total_credit, f"Entry {entry.entry_number} is unbalanced"

        # Verify total expense balance matches 300 (no duplicates)
        assert expense_acc.balance == 300

        # Verify debt accuracy
        assert debt.remaining == 30
