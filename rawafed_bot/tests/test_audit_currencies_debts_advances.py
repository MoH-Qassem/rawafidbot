"""Independent audit: multi-currency, debts, advances."""
import pytest

from rawafed_bot.accounting.ledger import (
    assert_all_entries_balanced,
    assert_stored_balances_match_ledger,
)
from rawafed_bot.database.models.debt import MemberDebt
from rawafed_bot.database.models.transaction import Transaction
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.services.operation_service import OperationError, OperationService
from rawafed_bot.tests.audit_helpers import cash, cat_id, currency_by_code, expense_acc, m, members


class TestCurrencyIsolationAudit:
    def test_three_currencies_independent(self, db):
        seed_all(db)
        mem = members(db)[0]
        cid = cat_id(db)
        OperationService.record_deposit(
            db, m(1000, "USD", db), currency_by_code(db, "USD").id, mem.id, "u", mem.id, "c-u"
        )
        OperationService.record_deposit(
            db, m(2000000, "SYP", db), currency_by_code(db, "SYP").id, mem.id, "s", mem.id, "c-s"
        )
        OperationService.record_deposit(
            db, m(500, "TRY", db), currency_by_code(db, "TRY").id, mem.id, "t", mem.id, "c-t"
        )
        OperationService.record_expense_from_box(
            db, m(200, "USD", db), currency_by_code(db, "USD").id, cid, mem.id, "eu", mem.id, "c-eu"
        )
        OperationService.record_expense_from_box(
            db, m(500000, "SYP", db), currency_by_code(db, "SYP").id, cid, mem.id, "es", mem.id, "c-es"
        )
        OperationService.record_expense_from_box(
            db, m(100, "TRY", db), currency_by_code(db, "TRY").id, cid, mem.id, "et", mem.id, "c-et"
        )
        assert cash(db, "USD").balance == m(800, "USD", db)
        assert cash(db, "SYP").balance == m(1500000, "SYP", db)
        assert cash(db, "TRY").balance == m(400, "TRY", db)
        assert_all_entries_balanced(db)
        assert_stored_balances_match_ledger(db)


class TestDebtAudit:
    def test_seeded_debt_partial_repayments(self, db):
        from rawafed_bot.tests._debt_seed import seed_member_debt

        seed_all(db)
        ahmad = members(db)[0]
        cur = currency_by_code(db, "USD")
        OperationService.record_deposit(
            db, m(500, "USD", db), cur.id, ahmad.id, "fund", ahmad.id, "d-fund"
        )
        # Record company expense that is also tracked as member debt
        pe = OperationService.record_expense_from_box(
            db, m(100, "USD", db), cur.id, cat_id(db), ahmad.id, "pers", ahmad.id, "d-pe"
        )
        debt = seed_member_debt(db, ahmad.id, cur.id, m(100, "USD", db), "d-debt-seed")
        debt.transaction_id = pe.id
        db.add(debt)
        db.commit()
        assert debt.remaining == m(100, "USD", db)
        assert expense_acc(db, "USD").balance == m(100, "USD", db)
        assert cash(db, "USD").balance == m(400, "USD", db)

        OperationService.record_debt_repayment(
            db, m(30, "USD", db), cur.id, ahmad.id, "r1", ahmad.id, debt.id, "d-r1"
        )
        OperationService.record_debt_repayment(
            db, m(20, "USD", db), cur.id, ahmad.id, "r2", ahmad.id, debt.id, "d-r2"
        )
        db.refresh(debt)
        assert debt.remaining == m(50, "USD", db)
        assert cash(db, "USD").balance == m(450, "USD", db)
        assert expense_acc(db, "USD").balance == m(50, "USD", db)

    def test_overpay_and_full_repay_and_reverse_repay(self, db):
        from rawafed_bot.tests._debt_seed import seed_member_debt

        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, "USD")
        OperationService.record_deposit(db, m(200, "USD", db), cur.id, mem.id, "d", mem.id, "dr-d")
        debt = seed_member_debt(db, mem.id, cur.id, m(80, "USD", db), "dr-debt")
        with pytest.raises(OperationError):
            OperationService.record_debt_repayment(
                db, m(81, "USD", db), cur.id, mem.id, "bad", mem.id, debt.id, "dr-bad"
            )
        repay = OperationService.record_debt_repayment(
            db, m(80, "USD", db), cur.id, mem.id, "full", mem.id, debt.id, "dr-full"
        )
        db.refresh(debt)
        assert debt.remaining == 0
        assert debt.status == "repaid"
        OperationService.reverse_transaction(db, repay.id, "إلغاء سداد", mem.id, "dr-rev")
        db.refresh(debt)
        assert debt.remaining == m(80, "USD", db)
        assert debt.status == "active"
        assert_stored_balances_match_ledger(db)

    def test_cannot_reverse_expense_after_partial_repay_on_linked_debt(self, db):
        from rawafed_bot.tests._debt_seed import seed_member_debt

        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, "USD")
        OperationService.record_deposit(db, m(100, "USD", db), cur.id, mem.id, "d", mem.id, "cr-d")
        pe = OperationService.record_expense_from_box(
            db, m(50, "USD", db), cur.id, cat_id(db), mem.id, "p", mem.id, "cr-p"
        )
        debt = seed_member_debt(db, mem.id, cur.id, m(50, "USD", db), "cr-debt")
        debt.transaction_id = pe.id
        db.add(debt)
        db.commit()
        OperationService.record_debt_repayment(
            db, m(10, "USD", db), cur.id, mem.id, "r", mem.id, debt.id, "cr-r"
        )
        with pytest.raises(OperationError):
            OperationService.reverse_transaction(db, pe.id, "لا", mem.id, "cr-rev")


class TestAdvanceAudit:
    def test_advance_settle_net_cash_drop_300(self, db):
        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, "USD")
        OperationService.record_deposit(db, m(1000, "USD", db), cur.id, mem.id, "d", mem.id, "ad-d")
        before = cash(db, "USD").balance
        tx, advance = OperationService.record_withdrawal_as_advance(
            db, m(500, "USD", db), cur.id, mem.id, "adv", "شراء", mem.id, "ad-a"
        )
        assert cash(db, "USD").balance == before - m(500, "USD", db)
        assert expense_acc(db, "USD").balance == 0
        OperationService.settle_advance(
            db, advance.id, m(300, "USD", db), m(200, "USD", db), "settle", mem.id,
            category_id=cat_id(db), idempotency_key="ad-s",
        )
        db.refresh(advance)
        assert advance.status == "fully_settled"
        assert expense_acc(db, "USD").balance == m(300, "USD", db)
        assert cash(db, "USD").balance == before - m(300, "USD", db)
        from rawafed_bot.database.models.account import Account
        adv_acc = db.query(Account).filter_by(
            account_type="advance_pending", member_id=mem.id, currency_id=cur.id
        ).one()
        assert adv_acc.balance == 0
        assert_stored_balances_match_ledger(db)

    def test_settle_over_advance_rejected(self, db):
        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, "USD")
        OperationService.record_deposit(db, m(500, "USD", db), cur.id, mem.id, "d", mem.id, "ao-d")
        _, advance = OperationService.record_withdrawal_as_advance(
            db, m(100, "USD", db), cur.id, mem.id, "a", "p", mem.id, "ao-a"
        )
        with pytest.raises(OperationError):
            OperationService.settle_advance(
                db, advance.id, m(80, "USD", db), m(30, "USD", db), "bad", mem.id,
                idempotency_key="ao-s",
            )
