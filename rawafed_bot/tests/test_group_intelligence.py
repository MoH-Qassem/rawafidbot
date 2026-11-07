"""Group intelligence, onboarding, addressing, and intent routing tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from rawafed_bot.core.config import settings
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.role import Role
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.services.addressing import is_addressed_to_accountant, is_bot_message, strip_address_prefix
from rawafed_bot.services.intent_router import IntentRouter
from rawafed_bot.services.member_service import MemberService
from rawafed_bot.services.onboarding_service import OnboardingService
from rawafed_bot.services.permission_service import PermissionService
from rawafed_bot.services.permissions_catalog import CREATE_CONTRIBUTION, RECORD_DEPOSIT, VIEW_CASHBOX
from rawafed_bot.services.registration_service import RegistrationError, RegistrationService
from rawafed_bot.bot.app import create_dispatcher


def _msg(text: str, *, user_id: int = 222222222, is_bot: bool = False, chat_type: str = "supergroup"):
    m = MagicMock()
    m.text = text
    m.caption = None
    m.entities = None
    m.caption_entities = None
    m.reply_to_message = None
    m.from_user = MagicMock(id=user_id, is_bot=is_bot, full_name="Test User", username="tu")
    m.chat = MagicMock(type=chat_type, id=-1001)
    m.reply = AsyncMock()
    m.answer = AsyncMock()
    return m


class TestAddressing:
    def test_ya_mohaseb_addressed(self):
        assert is_addressed_to_accountant(_msg("يا محاسب، كم الرصيد؟"))

    def test_bare_word_in_chat_not_addressed(self):
        assert not is_addressed_to_accountant(
            _msg("ذهب المحاسب إلى الاجتماع الساعة الخامسة")
        )

    def test_bot_own_message_ignored(self):
        assert is_bot_message(_msg("مرحبا", is_bot=True))
        assert not is_addressed_to_accountant(_msg("يا محاسب", is_bot=True))

    def test_strip_prefix(self):
        assert "كم الرصيد" in strip_address_prefix("يا محاسب، كم الرصيد؟")


class TestOnboarding:
    def test_first_contact_invite_once(self, db):
        seed_all(db)
        for m in db.query(Member).filter(Member.is_ceo == False).all():
            m.is_active = False
            db.add(m)
        db.commit()
        tid = 800000101
        should, reason = OnboardingService.should_invite(db, tid)
        assert should and reason == "ok"
        OnboardingService.mark_invited(db, tid, -1001)
        should2, reason2 = OnboardingService.should_invite(db, tid)
        assert not should2 and reason2 == "already_invited"

    def test_choose_accountant_title_no_extra_perms(self, db):
        seed_all(db)
        for m in db.query(Member).filter(Member.is_ceo == False).all():
            m.is_active = False
            db.add(m)
        db.commit()
        mem = OnboardingService.apply_job_title_choice(
            db, 800000102, "accountant", telegram_full_name="Ali"
        )
        assert mem.job_title == "محاسب"
        assert mem.is_ceo is False
        assert not PermissionService.has_permission(db, mem, CREATE_CONTRIBUTION)
        assert PermissionService.has_permission(db, mem, RECORD_DEPOSIT)

    def test_choose_custom_title(self, db):
        seed_all(db)
        for m in db.query(Member).filter(Member.is_ceo == False).all():
            m.is_active = False
            db.add(m)
        db.commit()
        mem = OnboardingService.apply_job_title_choice(
            db, 800000103, "other", custom_title="مستشار قانوني"
        )
        assert mem.job_title == "مستشار قانوني"

    def test_choose_ceo_title_does_not_grant_ceo(self, db):
        seed_all(db)
        for m in db.query(Member).filter(Member.is_ceo == False).all():
            m.is_active = False
            db.add(m)
        db.commit()
        mem = OnboardingService.apply_job_title_choice(
            db, 800000104, "ceo_title", telegram_full_name="X"
        )
        assert "CEO" in (mem.job_title or "")
        assert mem.is_ceo is False
        assert not PermissionService.has_permission(db, mem, CREATE_CONTRIBUTION)

    def test_fifth_ok_sixth_rejected(self, db):
        seed_all(db)
        for m in db.query(Member).filter(Member.is_ceo == False).all():
            m.is_active = False
            db.add(m)
        db.commit()
        # CEO active + 4 new = 5
        for i, tid in enumerate([800000201, 800000202, 800000203, 800000204]):
            OnboardingService.apply_job_title_choice(db, tid, "staff", telegram_full_name=f"U{i}")
        assert RegistrationService.active_count(db) == 5
        with pytest.raises(RegistrationError):
            OnboardingService.apply_job_title_choice(
                db, 800000205, "staff", telegram_full_name="Sixth"
            )

    def test_duplicate_register_blocked(self, db):
        seed_all(db)
        for m in db.query(Member).filter(Member.is_ceo == False).all():
            m.is_active = False
            db.add(m)
        db.commit()
        OnboardingService.apply_job_title_choice(db, 800000301, "board", telegram_full_name="A")
        with pytest.raises(RegistrationError):
            OnboardingService.apply_job_title_choice(db, 800000301, "staff", telegram_full_name="A")


class TestProfileAndPermissionsStable:
    def test_change_job_title_keeps_permissions(self, db):
        seed_all(db)
        mem = db.query(Member).filter_by(is_ceo=False, is_active=True).first()
        before = PermissionService.member_permission_codes(db, mem)
        role_before = PermissionService.get_member_role(db, mem.id)
        MemberService.update_profile(db, mem.id, job_title="لقب جديد")
        db.refresh(mem)
        assert mem.job_title == "لقب جديد"
        assert PermissionService.member_permission_codes(db, mem) == before
        role_after = PermissionService.get_member_role(db, mem.id)
        assert (role_before.id if role_before else None) == (role_after.id if role_after else None)

    def test_profile_card_contains_fields(self, db):
        seed_all(db)
        mem = db.query(Member).filter_by(is_ceo=True).first()
        card = MemberService.profile_card(db, mem)
        assert "Telegram ID" in card
        assert "المنصب الرسمي" in card


class TestIntents:
    def test_cashbox_question(self, db):
        seed_all(db)
        mem = db.query(Member).filter_by(is_active=True).first()
        assert PermissionService.has_permission(db, mem, VIEW_CASHBOX)
        result = IntentRouter.route(db, mem, "يا محاسب، كم رصيد الصندوق؟", "أحمد")
        assert result.intent == "cashbox"
        assert "رصيد" in result.reply or "$" in result.reply or "USD" in result.reply or "صندوق" in result.reply

    def test_expense_routes_to_write_op(self, db):
        seed_all(db)
        mem = db.query(Member).filter_by(is_active=True).first()
        result = IntentRouter.route(
            db, mem, "يا محاسب، سجل 50 ليرة سورية مصروف أوراق", "أحمد"
        )
        assert result.intent == "write_op"
        assert result.parsed_op is not None
        assert result.parsed_op.op_type == "expense"

    def test_unauthorized_denied(self, db):
        seed_all(db)
        mem = db.query(Member).filter_by(is_ceo=False, is_active=True).first()
        board = db.query(Role).filter_by(code="board_member").one()
        ceo = db.query(Member).filter_by(is_ceo=True).one()
        PermissionService.assign_role(db, mem.id, board.id, ceo.id)
        PermissionService.set_role_permission(db, board.id, VIEW_CASHBOX, False, ceo)
        db.refresh(mem)
        result = IntentRouter.route(db, mem, "يا محاسب كم رصيد الصندوق", "س")
        assert result.intent == "denied"

    def test_ignore_unrelated_after_strip(self, db):
        seed_all(db)
        mem = db.query(Member).filter_by(is_active=True).first()
        result = IntentRouter.route(db, mem, "يا محاسب، طقس اليوم جميل", "س")
        assert result.intent in {"unknown", "help"}


@pytest.mark.asyncio
class TestGroupHandlerBehaviour:
    async def test_registered_addressed_replies(self, db, monkeypatch):
        seed_all(db)
        from rawafed_bot.bot.handlers import group_chat as gc

        mem = db.query(Member).filter_by(telegram_id=settings.MEMBER_TELEGRAM_IDS[1]).one()
        storage = MemoryStorage()
        state = FSMContext(
            storage=storage,
            key=StorageKey(bot_id=1, chat_id=-1001, user_id=mem.telegram_id),
        )
        bot = MagicMock()
        bot.id = 999
        bot.me = AsyncMock(return_value=MagicMock(username="rawafed_bot", id=999, is_bot=True))
        bot.send_message = AsyncMock()

        # Point handler DB to test session via monkeypatch of get_db_context
        from contextlib import contextmanager
        import rawafed_bot.bot.handlers.group_chat as mod

        @contextmanager
        def _ctx():
            yield db

        monkeypatch.setattr(mod, "get_db_context", _ctx)

        message = _msg("يا محاسب، كم رصيد الصندوق؟", user_id=mem.telegram_id)
        await gc.group_text_message(message, state, bot, member=mem)
        assert message.reply.await_count >= 1

    async def test_unrelated_group_chat_no_reply(self, db, monkeypatch):
        seed_all(db)
        from rawafed_bot.bot.handlers import group_chat as gc
        from contextlib import contextmanager

        mem = db.query(Member).filter_by(telegram_id=settings.MEMBER_TELEGRAM_IDS[1]).one()

        @contextmanager
        def _ctx():
            yield db

        monkeypatch.setattr(gc, "get_db_context", _ctx)
        storage = MemoryStorage()
        state = FSMContext(
            storage=storage,
            key=StorageKey(bot_id=1, chat_id=-1001, user_id=mem.telegram_id),
        )
        bot = MagicMock()
        bot.id = 999
        bot.me = AsyncMock(return_value=MagicMock(username="rawafed_bot", id=999))
        message = _msg("اجتماع الساعة خمسة بخصوص المحاسب السابق", user_id=mem.telegram_id)
        await gc.group_text_message(message, state, bot, member=mem)
        assert message.reply.await_count == 0

    async def test_fsm_isolation_keys(self):
        storage = MemoryStorage()
        s1 = FSMContext(
            storage=storage,
            key=StorageKey(bot_id=1, chat_id=1, user_id=111),
        )
        s2 = FSMContext(
            storage=storage,
            key=StorageKey(bot_id=1, chat_id=1, user_id=222),
        )
        await s1.set_state("OnboardingStates:waiting_custom_title")
        assert await s2.get_state() is None


class TestDispatcher:
    def test_group_chat_router_registered(self):
        dp = create_dispatcher()
        names = [r.name for r in dp.sub_routers]
        assert "group_chat" in names
        assert len(names) == len(set(names))

    def test_seed_twice_survives(self, db):
        seed_all(db)
        seed_all(db)
        assert db.query(Member).filter_by(is_ceo=True, is_active=True).count() == 1
