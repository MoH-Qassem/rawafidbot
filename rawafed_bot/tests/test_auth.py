"""Auth & Permission tests."""
import pytest
from rawafed_bot.services.auth_service import AuthService
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.core.config import settings


class TestAuthService:
    def test_is_known_user(self, db):
        seed_all(db)
        assert AuthService.is_known_user(db, settings.CEO_TELEGRAM_ID) is True
        assert AuthService.is_known_user(db, settings.MEMBER_TELEGRAM_IDS[1]) is True
        assert AuthService.is_known_user(db, 999999999) is False

    def test_is_ceo(self):
        assert AuthService.is_ceo(settings.CEO_TELEGRAM_ID) is True
        assert AuthService.is_ceo(settings.MEMBER_TELEGRAM_IDS[1]) is False

    def test_get_or_create_member(self, db):
        seed_all(db)
        member = AuthService.get_or_create_member(db, settings.CEO_TELEGRAM_ID)
        assert member is not None
        assert member.is_ceo is True
        member2 = AuthService.get_or_create_member(db, settings.CEO_TELEGRAM_ID)
        assert member2.id == member.id

    def test_get_or_create_member_unknown(self, db):
        seed_all(db)
        with pytest.raises(PermissionError):
            AuthService.get_or_create_member(db, 999999999)

    def test_require_member(self, db):
        seed_all(db)
        member = AuthService.require_member(db, settings.MEMBER_TELEGRAM_IDS[1])
        assert member is not None
        assert member.telegram_id == settings.MEMBER_TELEGRAM_IDS[1]

    def test_require_member_unknown(self, db):
        seed_all(db)
        with pytest.raises(PermissionError):
            AuthService.require_member(db, 888888888)

    def test_require_ceo(self, db):
        seed_all(db)
        ceo = AuthService.require_ceo(db, settings.CEO_TELEGRAM_ID)
        assert ceo.is_ceo is True

    def test_require_ceo_by_member(self, db):
        seed_all(db)
        with pytest.raises(PermissionError) as exc_info:
            AuthService.require_ceo(db, settings.MEMBER_TELEGRAM_IDS[1])
        assert "CEO" in str(exc_info.value)
