"""Group registration, roles, and permission gate tests (isolated DB)."""
from __future__ import annotations

import pytest

from rawafed_bot.accounting.ledger import assert_stored_balances_match_ledger
from rawafed_bot.bot.app import create_dispatcher
from rawafed_bot.core.config import settings
from rawafed_bot.database.models import AuditLog, Member
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.role import Role
from rawafed_bot.database.models.transaction import Transaction
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.services.auth_service import AuthService
from rawafed_bot.services.group_service import GroupError, GroupService
from rawafed_bot.services.operation_service import OperationError, OperationService
from rawafed_bot.services.permission_service import PermissionErrorDenied, PermissionService
from rawafed_bot.services.permissions_catalog import (
    CREATE_CONTRIBUTION,
    MANAGE_ROLES,
    RECORD_DEPOSIT,
    VIEW_CASHBOX,
)
from rawafed_bot.services.registration_service import RegistrationError, RegistrationService


class TestRegistration:
    def test_register_ceo_and_members_upto_five(self, db):
        seed_all(db)
        for m in db.query(Member).filter(Member.is_ceo == False).all():
            m.is_active = False
            db.add(m)
        db.commit()

        ceo = RegistrationService.ensure_ceo_member(db, "ceo_user", "CEO Name")
        assert ceo.is_ceo and ceo.is_active

        for i, tid in enumerate([700000001, 700000002, 700000003, 700000004]):
            RegistrationService.register_self(db, tid, f"u{i}", f"User {i}")
        assert RegistrationService.active_count(db) == 5
        with pytest.raises(RegistrationError):
            RegistrationService.register_self(db, 700000005, "u6", "Sixth")

    def test_duplicate_register_rejected(self, db):
        seed_all(db)
        for m in db.query(Member).filter(Member.is_ceo == False).all():
            m.is_active = False
            db.add(m)
        db.commit()
        RegistrationService.register_self(db, 710000001, "a", "A")
        with pytest.raises(RegistrationError):
            RegistrationService.register_self(db, 710000001, "a", "A")

    def test_unregistered_cannot_require_member(self, db):
        seed_all(db)
        with pytest.raises(PermissionError):
            AuthService.require_member(db, 888888888)

    def test_unregistered_cannot_record_expense(self, db):
        seed_all(db)
        usd = db.query(Currency).filter_by(code="USD").one()
        # Use a fake created_by that does not exist
        with pytest.raises(OperationError):
            OperationService.record_expense_from_box(
                db, 1000, usd.id, 1, 99999, "x", 99999, "no-user-exp"
            )

    def test_unregister_keeps_history_blocks_ceo(self, db):
        seed_all(db)
        ceo = AuthService.require_ceo(db, settings.CEO_TELEGRAM_ID)
        target = db.query(Member).filter_by(is_ceo=False, is_active=True).first()
        usd = db.query(Currency).filter_by(code="USD").one()
        OperationService.record_deposit(
            db, 1500, usd.id, target.id, "hist", target.id, "reg-hist-1"
        )
        RegistrationService.unregister_member(db, target.id, ceo, "test")
        db.refresh(target)
        assert target.is_active is False
        assert db.query(Transaction).filter_by(member_id=target.id).count() >= 1
        with pytest.raises(RegistrationError):
            RegistrationService.unregister_member(db, ceo.id, ceo, "no")

    def test_setup_welcome_once(self, db):
        seed_all(db)
        g1, send1 = GroupService.setup_group(
            db, chat_id=-1001, title="Rawafed", ceo_telegram_id=settings.CEO_TELEGRAM_ID
        )
        assert send1 is True
        g2, send2 = GroupService.setup_group(
            db, chat_id=-1001, title="Rawafed", ceo_telegram_id=settings.CEO_TELEGRAM_ID
        )
        assert send2 is False
        assert g1.id == g2.id
        with pytest.raises(GroupError):
            GroupService.setup_group(
                db, chat_id=-1002, title="X", ceo_telegram_id=222222222
            )

    def test_incomplete_registration_blocks_ops_when_group_setup(self, db):
        seed_all(db)
        for m in db.query(Member).filter(Member.is_ceo == False).all():
            m.is_active = False
            db.add(m)
        db.commit()
        GroupService.setup_group(
            db, chat_id=-2001, title="G", ceo_telegram_id=settings.CEO_TELEGRAM_ID
        )
        ceo = AuthService.require_ceo(db, settings.CEO_TELEGRAM_ID)
        usd = db.query(Currency).filter_by(code="USD").one()
        with pytest.raises(OperationError):
            OperationService.record_deposit(
                db, 1000, usd.id, ceo.id, "blocked", ceo.id, "blocked-dep-1"
            )


class TestRolesPermissions:
    def test_default_matrix_and_ceo_locked(self, db):
        seed_all(db)
        PermissionService.seed_catalog(db)
        ceo = AuthService.require_ceo(db, settings.CEO_TELEGRAM_ID)
        member = db.query(Member).filter_by(is_ceo=False, is_active=True).first()
        assert PermissionService.has_permission(db, ceo, CREATE_CONTRIBUTION)
        assert PermissionService.has_permission(db, member, RECORD_DEPOSIT)
        assert not PermissionService.has_permission(db, member, CREATE_CONTRIBUTION)
        assert not PermissionService.has_permission(db, member, MANAGE_ROLES)

        ceo_role = db.query(Role).filter_by(code="ceo").one()
        with pytest.raises(PermissionErrorDenied):
            PermissionService.set_role_permission(
                db, ceo_role.id, CREATE_CONTRIBUTION, False, ceo
            )

    def test_member_cannot_change_own_role_or_ceo(self, db):
        seed_all(db)
        PermissionService.seed_catalog(db)
        member = db.query(Member).filter_by(is_ceo=False, is_active=True).first()
        ceo = AuthService.require_ceo(db, settings.CEO_TELEGRAM_ID)
        board = db.query(Role).filter_by(code="accountant").one()
        with pytest.raises(PermissionErrorDenied):
            PermissionService.assign_role(db, member.id, board.id, member.id)
        with pytest.raises(PermissionErrorDenied):
            PermissionService.assign_role(db, ceo.id, board.id, ceo.id)

    def test_permission_change_applies_immediately_and_audited(self, db):
        seed_all(db)
        PermissionService.seed_catalog(db)
        ceo = AuthService.require_ceo(db, settings.CEO_TELEGRAM_ID)
        member = db.query(Member).filter_by(is_ceo=False, is_active=True).first()
        board = db.query(Role).filter_by(code="board_member").one()
        PermissionService.assign_role(db, member.id, board.id, ceo.id)
        assert PermissionService.has_permission(db, member, VIEW_CASHBOX)
        PermissionService.set_role_permission(db, board.id, VIEW_CASHBOX, False, ceo)
        db.refresh(member)
        assert not PermissionService.has_permission(db, member, VIEW_CASHBOX)
        assert db.query(AuditLog).filter_by(action="set_permission").count() >= 1

    def test_finance_still_balanced_with_permissions(self, db):
        seed_all(db)
        PermissionService.seed_catalog(db)
        mem = db.query(Member).filter_by(is_active=True).first()
        usd = db.query(Currency).filter_by(code="USD").one()
        assert PermissionService.has_permission(db, mem, RECORD_DEPOSIT) or mem.is_ceo
        OperationService.record_deposit(
            db, 2500, usd.id, mem.id, "perm-dep", mem.id, "perm-dep-1"
        )
        OperationService.record_expense_from_box(
            db, 500, usd.id, 1, mem.id, "perm-exp", mem.id, "perm-exp-1"
        )
        assert_stored_balances_match_ledger(db)


class TestRoutersIncludeGroup:
    def test_dispatcher_has_group_and_roles_routers(self):
        dp = create_dispatcher()
        names = [r.name for r in dp.sub_routers]
        assert "group_setup" in names
        assert "roles_admin" in names
        assert len(names) == len(set(names))
