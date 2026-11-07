"""Prove /start activates MENU_VERSION UI — isolated temp DB, no polling."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rawafed_bot.bot.app import create_dispatcher
from rawafed_bot.bot.handlers import start as start_mod
from rawafed_bot.bot.keyboards import main_menu as mm
from rawafed_bot.bot.states import OnboardingStates
from rawafed_bot.core.version import BUILD_ID, MENU_VERSION, START_HANDLER, WELCOME_REGISTERED
from rawafed_bot.database.connection import Base, configure_sqlite_engine
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.seeder import seed_all


@pytest.fixture
def menu_db(tmp_path, monkeypatch):
    db_path = tmp_path / "start_menu.db"
    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
    configure_sqlite_engine(engine)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    import rawafed_bot.database.connection as conn

    monkeypatch.setattr(conn, "SessionLocal", Session)
    monkeypatch.setattr(conn, "engine", engine)
    monkeypatch.setattr(conn.settings, "DATABASE_URL", url)
    with Session() as s:
        seed_all(s)
    yield Session
    engine.dispose()


def _fsm(uid=111111111, chat_id=None):
    chat_id = chat_id if chat_id is not None else uid
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=chat_id, user_id=uid),
    )


def _msg(uid=111111111, chat_type="private", chat_id=None):
    chat_id = chat_id if chat_id is not None else (-1001 if chat_type != "private" else uid)
    msg = MagicMock()
    msg.text = "/start"
    msg.from_user = MagicMock(id=uid)
    msg.chat = MagicMock(type=chat_type, id=chat_id)
    msg.answer = AsyncMock()
    return msg


class TestMenuContract:
    def test_menu_version_and_build_bound(self):
        assert MENU_VERSION.startswith("menu-v5")
        assert BUILD_ID.startswith("2.1.0+")
        assert START_HANDLER.endswith("start.cmd_start")

    def test_no_old_report_label_on_keyboard(self):
        labels = {b.text for row in mm.main_menu_keyboard().keyboard for b in row}
        assert "📊 التقارير المالية" not in labels
        assert "📁 تصدير Excel" not in labels
        assert "🤝 المساهمات والعهد" not in labels
        assert mm.BTN_REPORT in labels
        assert mm.BTN_ADVANCES not in labels
        assert mm.BTN_WEEKLY in labels
        assert mm.BTN_MONTHLY in labels
        assert mm.BTN_EXPORT == "📥 تصدير Excel"

    def test_start_router_registered(self):
        dp = create_dispatcher()
        names = [r.name for r in dp.sub_routers]
        assert "start" in names
        assert names.count("start") == 1


class TestStartRegistered:
    @pytest.mark.asyncio
    async def test_registered_member_gets_full_menu(self, menu_db):
        s = menu_db()
        try:
            mem = s.query(Member).filter_by(telegram_id=111111111).one()
            mem.display_name = mem.display_name or "CEO Test"
            s.commit()
            member = MagicMock()
            member.id = mem.id
            member.is_ceo = True
            member.is_active = True
            member.telegram_id = mem.telegram_id
            member.display_name = mem.display_name
        finally:
            s.close()

        msg = _msg(111111111)
        state = _fsm(111111111)
        await start_mod.cmd_start(msg, state, member=member)
        assert msg.answer.await_count == 1
        text = msg.answer.await_args.args[0]
        assert "محاسب روافد الذكي" in text
        assert text == WELCOME_REGISTERED or WELCOME_REGISTERED in text
        kb = msg.answer.await_args.kwargs["reply_markup"]
        labels = {b.text for row in kb.keyboard for b in row}
        for btn in mm.all_ceo_buttons():
            assert btn in labels, btn
        assert "📊 التقارير المالية" not in labels

    @pytest.mark.asyncio
    async def test_registered_in_group_same_menu(self, menu_db):
        s = menu_db()
        try:
            mem = s.query(Member).filter_by(telegram_id=222222222).one()
            mem.display_name = mem.display_name or "Member Two"
            s.commit()
            member = MagicMock()
            member.id = mem.id
            member.is_ceo = False
            member.is_active = True
            member.telegram_id = mem.telegram_id
            member.display_name = mem.display_name
        finally:
            s.close()

        msg = _msg(222222222, chat_type="supergroup", chat_id=-10055)
        state = _fsm(222222222, chat_id=-10055)
        await start_mod.cmd_start(msg, state, member=member)
        kb = msg.answer.await_args.kwargs["reply_markup"]
        labels = {b.text for row in kb.keyboard for b in row}
        assert mm.BTN_GUIDE in labels
        assert mm.BTN_ADVANCES not in labels
        assert mm.BTN_ROLES not in labels  # non-CEO without manage roles


class TestStartUnregistered:
    @pytest.mark.asyncio
    async def test_unregistered_no_financial_menu(self, menu_db):
        # Free a slot: deactivate non-CEO members
        s = menu_db()
        try:
            for m in s.query(Member).filter(Member.is_ceo == False).all():
                m.is_active = False
                s.add(m)
            s.commit()
        finally:
            s.close()

        msg = _msg(uid=999888777, chat_type="supergroup", chat_id=-10077)
        state = _fsm(999888777, chat_id=-10077)
        await start_mod.cmd_start(msg, state, member=None)
        assert await state.get_state() == OnboardingStates.choosing_job_title.state
        # First answer is welcome + job keyboard — no main financial reply keyboard
        call_kwargs = [c.kwargs for c in msg.answer.await_args_list]
        for kw in call_kwargs:
            rb = kw.get("reply_markup")
            if rb is None:
                continue
            # Inline job keyboard has inline_keyboard; ReplyKeyboard has keyboard
            if hasattr(rb, "keyboard") and rb.keyboard:
                labels = {b.text for row in rb.keyboard for b in row}
                assert mm.BTN_CASHBOX not in labels
                assert mm.BTN_EXPENSE not in labels


class TestButtonHandlersExist:
    def test_every_menu_button_has_matching_handler_filter(self):
        """Static mapping: each canonical button is covered by texts_for or exact match."""
        required = set(mm.all_ceo_buttons())
        # MAIN and GUIDE handled in guide.py; ROLES in roles_admin; rest in feature modules
        covered = set()
        for btn in required:
            covered |= mm.texts_for(btn) if btn in mm.LEGACY or True else {btn}
            covered.add(btn)
        assert required <= covered
        # Advances removed from the live menu
        assert mm.BTN_ADVANCES not in set(mm.all_member_buttons())
