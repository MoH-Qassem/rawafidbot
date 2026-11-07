"""Group-first NL financial operations and unique-role tests."""
from __future__ import annotations

import pytest

from rawafed_bot.accounting.ledger import assert_stored_balances_match_ledger
from rawafed_bot.core.config import settings
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.role import MemberRole, Role
from rawafed_bot.database.models.transaction import Transaction
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.services.intent_router import IntentRouter
from rawafed_bot.services.nl_operation_parser import NLOperationParser
from rawafed_bot.services.operation_service import OperationService
from rawafed_bot.services.permission_service import PermissionService
from rawafed_bot.services.registration_service import RegistrationService
from rawafed_bot.services.role_transfer_service import RoleTransferService
from rawafed_bot.bot.app import create_dispatcher


class TestNLParser:
    def test_expense_syp_arabic(self, db):
        seed_all(db)
        p = NLOperationParser.parse(db, "يا محاسب، سجل 50 ليرة سورية مصروف أوراق")
        assert p.op_type == "expense"
        assert p.currency_code == "SYP"
        assert p.amount_minor == 5000
        assert p.amount_text is not None
        assert (p.category_name in {"أوراق", "أخرى", "مكتب"}) or "أوراق" in (p.description or "")

    def test_expense_usd_english_digits(self, db):
        seed_all(db)
        p = NLOperationParser.parse(db, "محاسب سجل 100 دولار مصروف نقل")
        assert p.op_type == "expense"
        assert p.currency_code == "USD"
        assert p.amount_minor == 10000

    def test_expense_arabic_digits(self, db):
        seed_all(db)
        p = NLOperationParser.parse(db, "يا محاسب مصروف ٥٠ ليرة تركية ضيافة")
        assert p.op_type == "expense"
        assert p.currency_code == "TRY"
        assert p.amount_minor == 5000

    def test_deposit_parse(self, db):
        seed_all(db)
        p = NLOperationParser.parse(db, "يا محاسب، سجل إيداع 500 دولار")
        assert p.op_type == "deposit"
        assert p.currency_code == "USD"
        assert p.amount_minor == 50000

    def test_withdraw_parse(self, db):
        seed_all(db)
        p = NLOperationParser.parse(db, "محاسب، سجل سحب 100 دولار")
        assert p.op_type == "withdrawal"
        assert p.amount_minor == 10000

    def test_missing_currency(self, db):
        seed_all(db)
        p = NLOperationParser.parse(db, "يا محاسب سجل مصروف 50")
        assert "currency" in p.missing

    def test_intent_routes_to_write_op(self, db):
        seed_all(db)
        mem = db.query(Member).filter_by(is_active=True).first()
        r = IntentRouter.route(db, mem, "يا محاسب سجل 50 ليرة سورية مصروف أوراق", "أحمد")
        assert r.intent == "write_op"
        assert r.parsed_op is not None
        assert r.parsed_op.op_type == "expense"

    def test_no_private_redirect_in_help(self, db):
        seed_all(db)
        mem = db.query(Member).filter_by(is_active=True).first()
        r = IntentRouter.route(db, mem, "يا محاسب ساعدني", "أحمد")
        assert "الخاص" not in r.reply


class TestExecuteMatchesLedger:
    def test_expense_from_parsed_balances(self, db):
        seed_all(db)
        mem = db.query(Member).filter_by(is_ceo=True).first()
        p = NLOperationParser.parse(db, "سجل 25 دولار مصروف مواصلات")
        assert not p.missing
        OperationService.record_deposit(
            db, 10000, p.currency_id, mem.id, "seed", mem.id, "nl-dep-1"
        )
        tx = OperationService.record_expense_from_box(
            db,
            p.amount_minor,
            p.currency_id,
            p.category_id,
            mem.id,
            p.description or "مواصلات",
            mem.id,
            "nl-exp-1",
        )
        assert tx.id
        assert_stored_balances_match_ledger(db)


class TestUniqueRoles:
    def test_unique_role_cannot_duplicate(self, db):
        seed_all(db)
        RoleTransferService.ensure_extra_roles(db)
        ceo = db.query(Member).filter_by(is_ceo=True).one()
        m1 = db.query(Member).filter_by(is_ceo=False, is_active=True).first()
        m2 = db.query(Member).filter(
            Member.is_ceo == False, Member.is_active == True, Member.id != m1.id
        ).first()
        acc = db.query(Role).filter_by(code="accountant").one()
        PermissionService.assign_role(db, m1.id, acc.id, ceo.id)
        PermissionService.assign_role(db, m2.id, acc.id, ceo.id)
        holders = RoleTransferService.holders(db, acc.id)
        assert len(holders) == 1
        assert holders[0].id == m2.id

    def test_transfer_request_and_approve(self, db):
        seed_all(db)
        for m in db.query(Member).filter(Member.is_ceo == False).all():
            m.is_active = False
            db.add(m)
        db.commit()
        RoleTransferService.ensure_extra_roles(db)
        a = RegistrationService.register_self(db, 880000001, "a", "Ali")
        b = RegistrationService.register_self(db, 880000002, "b", "Bob")
        ceo = db.query(Member).filter_by(is_ceo=True).one()
        acc = db.query(Role).filter_by(code="accountant").one()
        PermissionService.assign_role(db, a.id, acc.id, ceo.id)
        note = RoleTransferService.maybe_request_on_title(db, b, "accountant")
        assert note and "مشغول" in note
        from rawafed_bot.database.models.role_transfer import RoleTransferRequest
        req = db.query(RoleTransferRequest).filter_by(status="pending").one()
        RoleTransferService.approve(db, req.id, ceo)
        holders = RoleTransferService.holders(db, acc.id)
        assert len(holders) == 1 and holders[0].id == b.id


class TestRouters:
    def test_group_ops_and_guide_routers(self):
        dp = create_dispatcher()
        names = [r.name for r in dp.sub_routers]
        assert "group_ops" in names
        assert "guide" in names
