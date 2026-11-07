"""Full button + money + registration scenario coverage (no live Telegram)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rawafed_bot.bot.handlers import (
    cashbox,
    contributions,
    debts,
    deposit,
    expense,
    guide,
    history,
    members,
    reports,
    start,
    withdrawal,
)
from rawafed_bot.bot.handlers import settings as settings_handlers
from rawafed_bot.bot.keyboards import main_menu as mm
from rawafed_bot.bot.keyboards.common import pack
from rawafed_bot.bot.states import (
    DepositStates,
    ExpenseStates,
    OnboardingStates,
    WithdrawalStates,
)
from rawafed_bot.core.config import settings
from rawafed_bot.database.connection import Base, configure_sqlite_engine
from rawafed_bot.database.models.account import Account
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.debt import MemberDebt
from rawafed_bot.database.models.expense_category import ExpenseCategory
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.services.auth_service import AuthService
from rawafed_bot.services.group_service import GroupService
from rawafed_bot.services.operation_service import OperationService
from rawafed_bot.services.onboarding_service import OnboardingService
from rawafed_bot.services.registration_service import RegistrationService
from rawafed_bot.utils.callbacks import CONFIRM, CUR, EXP_MODE, WD_MODE, CAT


@pytest.fixture()
def full_db(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'full.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
    configure_sqlite_engine(engine)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    import rawafed_bot.database.connection as conn

    monkeypatch.setattr(conn, "SessionLocal", Session)
    monkeypatch.setattr(conn, "engine", engine)
    monkeypatch.setattr(conn.settings, "DATABASE_URL", url)
    monkeypatch.setattr(conn.settings, "CEO_TELEGRAM_ID", settings.CEO_TELEGRAM_ID or 111111111)
    monkeypatch.setattr(settings, "CEO_TELEGRAM_ID", settings.CEO_TELEGRAM_ID or 111111111)

    with Session() as s:
        seed_all(s)
    yield Session
    engine.dispose()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _fsm(uid: int) -> FSMContext:
    storage = MemoryStorage()
    return FSMContext(storage=storage, key=StorageKey(bot_id=1, chat_id=uid, user_id=uid))


def _msg(text: str, uid: int):
    m = MagicMock()
    m.text = text
    m.from_user = MagicMock(id=uid, full_name="Test", username="t")
    m.chat = MagicMock(type="private", id=uid)
    m.answer = AsyncMock()
    m.answer_document = AsyncMock()
    m.reply = AsyncMock()
    return m


def _cb(data: str, uid: int):
    c = MagicMock()
    c.data = data
    c.from_user = MagicMock(id=uid)
    c.bot = MagicMock()
    c.bot.send_message = AsyncMock()
    c.message = MagicMock()
    c.message.chat = MagicMock(type="private", id=uid)
    c.message.edit_text = AsyncMock()
    c.message.answer = AsyncMock()
    c.message.answer_document = AsyncMock()
    c.answer = AsyncMock()
    return c


def _ceo(session) -> Member:
    ceo = AuthService.require_ceo(session, settings.CEO_TELEGRAM_ID)
    # Eager scalars then expunge so handlers survive closed sessions
    _ = (ceo.id, ceo.telegram_id, ceo.is_ceo, ceo.is_active, ceo.display_name)
    session.expunge(ceo)
    return ceo


class TestAllMenuButtons:
    def test_every_member_button_responds(self, full_db):
        session = full_db()
        ceo = _ceo(session)
        uid = ceo.telegram_id
        state = _fsm(uid)
        session.close()

        handlers = [
            (mm.BTN_CASHBOX, cashbox.show_cashbox),
            (mm.BTN_HISTORY, history.show_history),
            (mm.BTN_MEMBERS, members.show_members),
            (mm.BTN_DEBTS, debts.show_debts),
            (mm.BTN_REPORT, reports.report_financial),
            (mm.BTN_WEEKLY, reports.report_weekly),
            (mm.BTN_MONTHLY, reports.report_monthly),
            (mm.BTN_EXPORT, reports.export_excel),
            (mm.BTN_GUIDE, guide.open_guide),
            (mm.BTN_MAIN, guide.main_menu),
            (mm.BTN_MY_PROFILE, settings_handlers.profile_entry),
            (mm.BTN_SETTINGS, settings_handlers.settings_entry),
            (mm.BTN_CONTRIB, contributions.contrib_entry),
        ]
        for label, handler in handlers:
            msg = _msg(label, uid)
            _run(handler(msg, state, ceo) if "state" in handler.__code__.co_varnames else handler(msg, ceo))
            replied = msg.answer.await_count + msg.answer_document.await_count
            assert replied >= 1, f"no reply for {label}"

        # Starters that set FSM
        for label, handler in (
            (mm.BTN_EXPENSE, expense.start_expense),
            (mm.BTN_DEPOSIT, deposit.start_deposit),
            (mm.BTN_WITHDRAW, withdrawal.start_withdrawal),
        ):
            msg = _msg(label, uid)
            st = _fsm(uid)
            _run(handler(msg, st, ceo))
            assert msg.answer.await_count >= 1, f"no start for {label}"


class TestMoneyFlowsEndToEnd:
    def test_deposit_expense_box_personal_withdraw_debt_cycle(self, full_db):
        session = full_db()
        ceo = _ceo(session)
        usd = session.query(Currency).filter_by(code="USD").one()
        cat = session.query(ExpenseCategory).first()
        uid = ceo.telegram_id

        # Deposit
        OperationService.record_deposit(
            session, 10_000, usd.id, ceo.id, "إيداع تجريبي", ceo.id, "e2e-dep"
        )
        cash = session.query(Account).filter_by(account_type="cash_box", currency_id=usd.id).one()
        assert cash.balance == 10_000

        # Company expense
        OperationService.record_expense_from_box(
            session, 1_000, usd.id, cat.id, ceo.id, "مصروف شركة", ceo.id, "e2e-ex"
        )
        session.refresh(cash)
        assert cash.balance == 9_000

        # Pocket expense → company owes member; cash untouched
        OperationService.record_personal_expense(
            session, 500, usd.id, cat.id, ceo.id, "من الجيب", ceo.id, "e2e-pe"
        )
        session.refresh(cash)
        due = session.query(Account).filter_by(
            account_type="member_due", currency_id=usd.id, member_id=ceo.id
        ).one()
        assert cash.balance == 9_000
        assert due.balance == -500

        # Overdraft withdrawal allowed
        OperationService.record_withdrawal(
            session, 9_000, usd.id, ceo.id, "سحب زائد", ceo.id, "e2e-wd"
        )
        session.refresh(cash)
        assert cash.balance == 0
        session.close()

    def test_deposit_fsm_confirm(self, full_db):
        session = full_db()
        ceo = _ceo(session)
        usd = session.query(Currency).filter_by(code="USD").one()
        uid = ceo.telegram_id
        session.close()

        state = _fsm(uid)
        msg = _msg(mm.BTN_DEPOSIT, uid)
        _run(deposit.start_deposit(msg, state, ceo))
        assert _run(state.get_state()) == DepositStates.choosing_currency.state

        cb = _cb(pack(CUR, usd.id), uid)
        _run(deposit.choose_currency(cb, state))
        assert _run(state.get_state()) == DepositStates.entering_amount.state

        msg = _msg("٢٥٠٫٥", uid)  # Arabic digits
        _run(deposit.enter_amount(msg, state))
        assert _run(state.get_state()) == DepositStates.entering_description.state

        msg = _msg("إيداع عربي", uid)
        _run(deposit.enter_description(msg, state))
        assert _run(state.get_state()) == DepositStates.confirming.state

        cb = _cb(f"{CONFIRM}:deposit:yes", uid)
        _run(deposit.confirm_deposit(cb, state, ceo))
        session = full_db()
        cash = session.query(Account).filter_by(account_type="cash_box", currency_id=usd.id).one()
        assert cash.balance == 25050  # 250.50 USD minor
        session.close()

    def test_expense_fsm_both_modes(self, full_db):
        session = full_db()
        ceo = _ceo(session)
        usd = session.query(Currency).filter_by(code="USD").one()
        cat = session.query(ExpenseCategory).first()
        usd_id, cat_id = usd.id, cat.id
        uid = ceo.telegram_id
        OperationService.record_deposit(
            session, 50_000, usd_id, ceo.id, "fund", ceo.id, "fund-ex"
        )
        session.close()

        # Box mode
        state = _fsm(uid)
        _run(expense.start_expense(_msg(mm.BTN_EXPENSE, uid), state, ceo))
        _run(expense.choose_mode(_cb(pack(EXP_MODE, "box"), uid), state))
        _run(expense.choose_currency(_cb(pack(CUR, usd_id), uid), state))
        _run(expense.enter_amount(_msg("100", uid), state))
        _run(expense.choose_category(_cb(pack(CAT, cat_id), uid), state))
        _run(expense.enter_description(_msg("شركة", uid), state))
        _run(expense.confirm_expense(_cb(f"{CONFIRM}:expense:yes", uid), state, ceo))

        # Personal mode
        state = _fsm(uid)
        _run(expense.start_expense(_msg(mm.BTN_EXPENSE, uid), state, ceo))
        _run(expense.choose_mode(_cb(pack(EXP_MODE, "personal"), uid), state))
        _run(expense.choose_currency(_cb(pack(CUR, usd_id), uid), state))
        _run(expense.enter_amount(_msg("50", uid), state))
        _run(expense.choose_category(_cb(pack(CAT, cat_id), uid), state))
        _run(expense.enter_description(_msg("عضو", uid), state))
        _run(expense.confirm_expense(_cb(f"{CONFIRM}:expense:yes", uid), state, ceo))

        session = full_db()
        cash = session.query(Account).filter_by(account_type="cash_box", currency_id=usd_id).one()
        due = session.query(Account).filter_by(
            account_type="member_due", currency_id=usd_id, member_id=ceo.id
        ).one()
        # Only box mode (100.00) hits cash; pocket (50.00) credits member_due
        assert cash.balance == 50_000 - 10_000
        assert due.balance == -5_000
        assert session.query(MemberDebt).filter_by(status="active").count() == 0
        session.close()


class TestRegistrationAndSetup:
    def test_setup_register_onboarding_profile(self, full_db):
        session = full_db()
        ceo = _ceo(session)
        # Only CEO active
        for m in session.query(Member).filter(Member.is_ceo == False).all():
            m.is_active = False
            session.add(m)
        session.commit()

        sent, group = GroupService.setup_group(
            session, chat_id=-555001, title="روافد", ceo_telegram_id=ceo.telegram_id
        )
        assert group is not None

        # New member registers
        new_tid = 777000111
        mem = RegistrationService.register_self(
            session, new_tid, telegram_username="newguy", telegram_full_name="عضو جديد"
        )
        assert mem.is_active
        RegistrationService.complete_profile(
            session, mem.id, display_name="أحمد (أبو علي)", job_title="محاسب"
        )
        session.refresh(mem)
        assert mem.display_name == "أحمد (أبو علي)"
        assert mem.profile_completed is True

        # CEO can still operate with incomplete roster
        usd = session.query(Currency).filter_by(code="USD").one()
        OperationService.record_deposit(
            session, 1000, usd.id, ceo.id, "بعد التسجيل الجزئي", ceo.id, "partial-ok"
        )
        session.close()

    def test_start_unregistered_begins_onboarding(self, full_db, monkeypatch):
        session = full_db()
        # Free a seat so a new user can start onboarding
        for m in session.query(Member).filter(Member.is_ceo == False).all():
            m.is_active = False
            session.add(m)
        session.commit()
        tid = 888777666
        monkeypatch.setattr(settings, "CEO_TELEGRAM_ID", 111111111)
        session.close()

        state = _fsm(tid)
        msg = _msg("/start", tid)
        _run(start.cmd_start(msg, state, member=None))
        assert msg.answer.await_count >= 1
        assert _run(state.get_state()) == OnboardingStates.choosing_job_title.state


class TestDebtsButtonNoShadow:
    def test_debts_keeps_caller_ceo_keyboard(self, full_db):
        session = full_db()
        ceo = _ceo(session)
        other = session.query(Member).filter_by(is_ceo=False, is_active=True).first()
        usd = session.query(Currency).filter_by(code="USD").one()
        cat = session.query(ExpenseCategory).first()
        OperationService.record_deposit(
            session, 5000, usd.id, ceo.id, "d", ceo.id, "debt-d"
        )
        OperationService.record_personal_expense(
            session, 1000, usd.id, cat.id, other.id, "debt on other", ceo.id, "debt-pe"
        )
        uid = ceo.telegram_id
        session.close()

        msg = _msg(mm.BTN_DEBTS, uid)
        _run(debts.show_debts(msg, _fsm(uid), ceo))
        # First answer is the report with caller's CEO keyboard
        kb = msg.answer.await_args_list[0].kwargs.get("reply_markup") or msg.answer.await_args_list[0][1].get("reply_markup")
        # args may be positional
        if kb is None:
            kb = msg.answer.await_args_list[0].args[1] if len(msg.answer.await_args_list[0].args) > 1 else None
        labels = {b.text for row in kb.keyboard for b in row}
        assert mm.BTN_ROLES in labels
