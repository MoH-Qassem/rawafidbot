"""CEO ensure idempotency and seeder restart safety (isolated DB)."""
from __future__ import annotations

import pytest

from rawafed_bot.core.config import settings
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.seeder import seed_all, seed_members
from rawafed_bot.services.registration_service import RegistrationError, RegistrationService


class TestEnsureCeoIdempotent:
    def test_ceo_exists_ensure_twice(self, db):
        seed_all(db)
        a = RegistrationService.ensure_ceo_member(db, "ceo", "CEO")
        b = RegistrationService.ensure_ceo_member(db, "ceo2", "CEO2")
        assert a.id == b.id
        assert b.is_ceo is True
        assert b.is_active is True
        assert db.query(Member).filter_by(is_ceo=True, is_active=True).count() == 1

    def test_ceo_missing_on_empty_db_creates(self, db, monkeypatch):
        monkeypatch.setattr(settings, "CEO_TELEGRAM_ID", 900000001)
        monkeypatch.setattr(settings, "MEMBER_TELEGRAM_IDS", [])
        member = RegistrationService.ensure_ceo_member(db)
        assert member.telegram_id == 900000001
        assert member.is_ceo is True
        assert RegistrationService.active_count(db) == 1

    def test_five_members_including_ceo_ok(self, db):
        seed_all(db)
        assert RegistrationService.active_count(db) == 5
        ceo = RegistrationService.ensure_ceo_member(db)
        assert ceo.is_ceo is True
        assert RegistrationService.active_count(db) == 5

    def test_sixth_member_rejected(self, db, monkeypatch):
        seed_all(db)
        assert RegistrationService.active_count(db) == 5
        with pytest.raises(RegistrationError):
            RegistrationService.register_self(db, 800000099, "x", "Sixth")

    def test_seed_all_twice_does_not_fail(self, db):
        seed_all(db)
        seed_all(db)
        seed_members(db)
        assert db.query(Member).filter_by(is_ceo=True, is_active=True).count() == 1
        assert RegistrationService.active_count(db) <= settings.MAX_MEMBERS


class TestPlaceholderConflictRemediation:
    def test_remediate_when_placeholders_full_and_ledger_empty(self, db, monkeypatch):
        monkeypatch.setattr(settings, "CEO_TELEGRAM_ID", 910000010)
        monkeypatch.setattr(
            settings,
            "MEMBER_TELEGRAM_IDS",
            [910000001, 910000002, 910000003, 910000004, 910000005],
        )
        for tid in settings.MEMBER_TELEGRAM_IDS:
            db.add(Member(telegram_id=tid, is_ceo=False, is_active=True))
        db.commit()
        assert RegistrationService.active_count(db) == 5

        with pytest.raises(RegistrationError):
            RegistrationService.ensure_ceo_member(db)

        assert RegistrationService.try_remediate_env_placeholder_conflict(db) is True
        ceo = RegistrationService.ensure_ceo_member(db)
        assert ceo.telegram_id == 910000010
        assert ceo.is_active is True
        assert RegistrationService.active_count(db) == 1
        # Rows preserved (soft deactivate)
        assert db.query(Member).count() == 6

    def test_no_remediate_when_financial_data_exists(self, db, monkeypatch):
        monkeypatch.setattr(settings, "CEO_TELEGRAM_ID", 920000010)
        monkeypatch.setattr(
            settings,
            "MEMBER_TELEGRAM_IDS",
            [920000001, 920000002, 920000003, 920000004, 920000005],
        )
        for tid in settings.MEMBER_TELEGRAM_IDS:
            db.add(Member(telegram_id=tid, is_ceo=False, is_active=True))
        db.commit()

        real_execute = db.execute

        def execute_with_ledger(stmt, *args, **kwargs):
            sql = str(stmt).lower()
            if "from transactions" in sql:
                class _R:
                    def scalar(self_inner):
                        return 1
                return _R()
            return real_execute(stmt, *args, **kwargs)

        monkeypatch.setattr(db, "execute", execute_with_ledger)
        assert RegistrationService.try_remediate_env_placeholder_conflict(db) is False
        with pytest.raises(RegistrationError):
            RegistrationService.ensure_ceo_member(db)
        assert RegistrationService.active_count(db) == 5

    def test_seed_members_repairs_placeholder_conflict(self, db, monkeypatch):
        monkeypatch.setattr(settings, "CEO_TELEGRAM_ID", 930000010)
        placeholders = [930000001, 930000002, 930000003, 930000004, 930000005]
        monkeypatch.setattr(settings, "MEMBER_TELEGRAM_IDS", placeholders)
        for tid in placeholders:
            db.add(Member(telegram_id=tid, is_ceo=False, is_active=True))
        db.commit()
        seed_members(db)
        ceo = db.query(Member).filter_by(telegram_id=930000010, is_active=True).one()
        assert ceo.is_ceo is True
        # Placeholders not reactivated
        assert RegistrationService.active_count(db) == 1
