"""Independent audit: deposits & expenses with human amounts."""
import pytest

from rawafed_bot.accounting.ledger import (
    assert_all_entries_balanced,
    assert_stored_balances_match_ledger,
)
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.services.operation_service import OperationError, OperationService
from rawafed_bot.services.contribution_service import ContributionService
from rawafed_bot.services.auth_service import AuthService
from rawafed_bot.tests.audit_helpers import cash, cat_id, currency_by_code, m, members
from rawafed_bot.utils.money import MoneyError, parse_user_amount


class TestDepositAudit:
    def test_five_deposits_usd_total_1400_01(self, db):
        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, "USD")
        amounts = ["100", "250", "50", "1000", "0.01"]
        for i, a in enumerate(amounts):
            OperationService.record_deposit(
                db, m(a, "USD", db), cur.id, mem.id, f"dep-{i}", mem.id,
                idempotency_key=f"audit-dep-usd-{i}",
            )
        assert cash(db, "USD").balance == m("1400.01", "USD", db)
        assert_all_entries_balanced(db)
        assert_stored_balances_match_ledger(db)

    @pytest.mark.parametrize("code", ["USD", "SYP", "TRY"])
    def test_deposit_sequence_per_currency(self, db, code):
        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, code)
        for i, a in enumerate(["100", "250", "50", "1000", "0.01"]):
            OperationService.record_deposit(
                db, m(a, code, db), cur.id, mem.id, f"{code}-{i}", mem.id,
                idempotency_key=f"audit-dep-{code}-{i}",
            )
        assert cash(db, code).balance == m("1400.01", code, db)
        # other currencies untouched
        for other in ["USD", "SYP", "TRY"]:
            if other != code:
                assert cash(db, other).balance == 0

    def test_multi_member_deposits(self, db):
        seed_all(db)
        ms = members(db)
        cur = currency_by_code(db, "USD")
        OperationService.record_deposit(db, m(100, "USD", db), cur.id, ms[0].id, "a", ms[0].id, "mm1")
        OperationService.record_deposit(db, m(200, "USD", db), cur.id, ms[1].id, "b", ms[1].id, "mm2")
        assert cash(db, "USD").balance == m(300, "USD", db)

    def test_contribution_partial_payment_and_cap(self, db):
        seed_all(db)
        ceo = AuthService.get_member_by_telegram_id(db, 111111111)
        payee = members(db)[1]
        cur = currency_by_code(db, "USD")
        req = ContributionService.create_request(
            db, m(100, "USD", db), cur.id, [payee.id], ceo.telegram_id, "مساهمة تدقيق",
        )
        assert cash(db, "USD").balance == 0  # unpaid not in cash
        ob = ContributionService.get_obligations(db, req.id)[0]
        ContributionService.pay_obligation(db, ob.id, m(40, "USD", db), payee.id, idempotency_key="cp1")
        assert cash(db, "USD").balance == m(40, "USD", db)
        db.refresh(ob)
        assert ob.paid_amount == m(40, "USD", db)
        with pytest.raises(OperationError):
            ContributionService.pay_obligation(db, ob.id, m(70, "USD", db), payee.id, idempotency_key="cp2")
        ContributionService.pay_obligation(db, ob.id, m(60, "USD", db), payee.id, idempotency_key="cp3")
        assert cash(db, "USD").balance == m(100, "USD", db)

    def test_invalid_and_duplicate_deposit(self, db):
        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, "USD")
        with pytest.raises(OperationError):
            OperationService.record_deposit(db, 0, cur.id, mem.id, "z", mem.id)
        with pytest.raises(MoneyError):
            parse_user_amount("-5", cur)
        OperationService.record_deposit(
            db, m(10, "USD", db), cur.id, mem.id, "once", mem.id, idempotency_key="dup-key"
        )
        with pytest.raises(OperationError):
            OperationService.record_deposit(
                db, m(10, "USD", db), cur.id, mem.id, "once", mem.id, idempotency_key="dup-key"
            )
        assert cash(db, "USD").balance == m(10, "USD", db)


class TestExpenseAudit:
    def test_expense_sequence_ends_500(self, db):
        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, "USD")
        cid = cat_id(db)
        OperationService.record_deposit(
            db, m(1000, "USD", db), cur.id, mem.id, "base", mem.id, "ex-base"
        )
        for i, a in enumerate(["100", "250", "0.50", "149.50"]):
            OperationService.record_expense_from_box(
                db, m(a, "USD", db), cur.id, cid, mem.id, f"e-{i}", mem.id, f"ex-{i}"
            )
        assert cash(db, "USD").balance == m(500, "USD", db)
        from rawafed_bot.tests.audit_helpers import expense_acc
        assert expense_acc(db, "USD").balance == m(500, "USD", db)
        assert_stored_balances_match_ledger(db)

    def test_personal_expense_from_pocket_credits_member_due(self, db):
        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, "USD")
        OperationService.record_deposit(db, m(100, "USD", db), cur.id, mem.id, "d", mem.id, "pe-d")
        OperationService.record_personal_expense(
            db, m(25, "USD", db), cur.id, cat_id(db), mem.id, "pers", mem.id, "pe-1"
        )
        # Cash untouched; company owes member
        assert cash(db, "USD").balance == m(100, "USD", db)
        from rawafed_bot.database.models.account import Account
        due = db.query(Account).filter_by(
            account_type="member_due", currency_id=cur.id, member_id=mem.id
        ).one()
        assert due.balance == -m(25, "USD", db)

    def test_expense_over_cash_allowed_negative_balance(self, db):
        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, "USD")
        OperationService.record_deposit(db, m(50, "USD", db), cur.id, mem.id, "d", mem.id, "ov-d")
        OperationService.record_expense_from_box(
            db, m(51, "USD", db), cur.id, cat_id(db), mem.id, "big", mem.id, "ov-e"
        )
        assert cash(db, "USD").balance == -m(1, "USD", db)

    def test_reverse_expense_restores_cash(self, db):
        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, "USD")
        OperationService.record_deposit(db, m(200, "USD", db), cur.id, mem.id, "d", mem.id, "rx-d")
        tx = OperationService.record_expense_from_box(
            db, m(75, "USD", db), cur.id, cat_id(db), mem.id, "e", mem.id, "rx-e"
        )
        assert cash(db, "USD").balance == m(125, "USD", db)
        OperationService.reverse_transaction(db, tx.id, "خطأ", mem.id, "rx-rev")
        assert cash(db, "USD").balance == m(200, "USD", db)
        assert_stored_balances_match_ledger(db)
