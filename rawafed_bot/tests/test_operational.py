"""Operational verification: routers, FSM flows, auth, reports, backup, persistence.

Uses an isolated SQLite file — never the production database.
Does not start Telegram polling or send real messages.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from openpyxl import load_workbook
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from zoneinfo import ZoneInfo

from rawafed_bot.accounting.ledger import assert_stored_balances_match_ledger
from rawafed_bot.bot.app import create_dispatcher
from rawafed_bot.bot.keyboards import main_menu as mm
from rawafed_bot.bot.states import DepositStates, ExpenseStates, SettingsStates
from rawafed_bot.core.config import settings
from rawafed_bot.database.connection import Base, configure_sqlite_engine
from rawafed_bot.database.models import Account, JournalEntry, JournalLine, Member, Transaction
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.reports.generator import ReportGenerator
from rawafed_bot.scheduler.jobs import _apscheduler_weekday, create_scheduler
from rawafed_bot.services.auth_service import AuthService
from rawafed_bot.services.backup_service import BackupService
from rawafed_bot.services.contribution_service import ContributionService
from rawafed_bot.services.operation_service import OperationService
from rawafed_bot.services.report_service import ReportService
from rawafed_bot.utils.money import find_currency, format_amount, parse_user_amount


MENU_BUTTONS = mm.all_member_buttons()


@pytest.fixture
def op_db(tmp_path, monkeypatch):
    """Isolated operational DB; redirect SessionLocal used by handlers."""
    db_path = tmp_path / "operational.db"
    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
    configure_sqlite_engine(engine)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    import rawafed_bot.database.connection as conn

    monkeypatch.setattr(conn, "SessionLocal", Session)
    monkeypatch.setattr(conn, "engine", engine)
    monkeypatch.setattr(conn.settings, "DATABASE_URL", url)

    with Session() as session:
        seed_all(session)
    # Do not keep a long-lived connection open — handlers open their own
    # BEGIN IMMEDIATE sessions and would otherwise hit "database is locked".
    yield db_path, Session
    engine.dispose()


def _session(op_db):
    _, Session = op_db
    return Session()


def _fsm(user_id: int = 111111111) -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _message(text: str = "", user_id: int = 111111111) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.from_user = MagicMock(id=user_id)
    msg.chat = MagicMock(type="private", id=user_id)
    msg.answer = AsyncMock()
    msg.answer_document = AsyncMock()
    return msg


def _callback(data: str, user_id: int = 111111111) -> MagicMock:
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock(id=user_id)
    cb.bot = MagicMock()
    cb.bot.send_message = AsyncMock()
    cb.message = MagicMock()
    cb.message.chat = MagicMock(type="private", id=user_id)
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.message.answer_document = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def _member(session, telegram_id: int = 111111111) -> Member:
    return session.query(Member).filter_by(telegram_id=telegram_id).one()


class TestBootAndRouters:
    def test_routers_unique_names(self):
        dp = create_dispatcher()
        names = [r.name for r in dp.sub_routers]
        assert len(names) == 18
        assert len(set(names)) == 18
        assert "start" in names and "group_ops" in names and "guide" in names
        assert names[-1] == "group_noise"

    def test_menu_buttons_present(self):
        kb = mm.main_menu_keyboard()
        labels = {btn.text for row in kb.keyboard for btn in row}
        assert labels == set(MENU_BUTTONS)
        ceo_kb = mm.main_menu_keyboard(is_ceo=True)
        ceo_labels = {btn.text for row in ceo_kb.keyboard for btn in row}
        assert mm.BTN_ROLES in ceo_labels

    def test_settings_flag_without_exposing_secrets(self):
        assert isinstance(settings.is_valid, bool)
        assert settings.CEO_TELEGRAM_ID != 0
        assert bool(settings.BOT_TOKEN)


class TestAuthPermissions:
    def test_five_members_and_ceo(self, op_db):
        session = _session(op_db)
        try:
            ms = AuthService.get_all_members(session)
            assert len(ms) == 5
            ceos = [m for m in ms if m.is_ceo]
            assert len(ceos) == 1
            assert ceos[0].telegram_id == 111111111
        finally:
            session.close()

    def test_unknown_user_rejected(self, op_db):
        session = _session(op_db)
        try:
            with pytest.raises(PermissionError):
                AuthService.require_member(session, 999999999)
        finally:
            session.close()

    def test_non_ceo_cannot_create_contribution(self, op_db):
        session = _session(op_db)
        try:
            non_ceo = session.query(Member).filter_by(is_ceo=False).first()
            cur = session.query(Currency).filter_by(code="USD").one()
            with pytest.raises(PermissionError):
                ContributionService.create_request(
                    session, 1000, cur.id, [non_ceo.id], non_ceo.telegram_id, "x"
                )
        finally:
            session.close()

    def test_ceo_can_create_contribution(self, op_db):
        session = _session(op_db)
        try:
            ceo = _member(session)
            other = session.query(Member).filter_by(is_ceo=False).first()
            cur = session.query(Currency).filter_by(code="USD").one()
            req = ContributionService.create_request(
                session, 1000, cur.id, [other.id], ceo.telegram_id, "ceo-ok"
            )
            assert req.id is not None
        finally:
            session.close()


@pytest.mark.asyncio
class TestTenButtonsAndFSM:
    async def test_each_button_handler_responds(self, op_db):
        session = _session(op_db)
        try:
            real = _member(session)
            member = MagicMock()
            member.id = real.id
            member.is_ceo = real.is_ceo
            member.telegram_id = real.telegram_id
            member.display_name = real.display_name
            member.job_title = real.job_title
            member.get_display_name = real.get_display_name
        finally:
            session.close()
        state = _fsm()

        from rawafed_bot.bot.handlers import (
            cashbox, contributions, debts, deposit, expense, history,
            members, reports, settings, withdrawal,
        )

        starters = [
            (mm.BTN_CASHBOX, cashbox.show_cashbox, False),
            (mm.BTN_EXPENSE, expense.start_expense, True),
            (mm.BTN_DEPOSIT, deposit.start_deposit, True),
            (mm.BTN_WITHDRAW, withdrawal.start_withdrawal, True),
            (mm.BTN_DEBTS, debts.show_debts, True),
            (mm.BTN_MEMBERS, members.show_members, True),
            (mm.BTN_HISTORY, history.show_history, False),
            (mm.BTN_REPORT, reports.report_financial, True),
            (mm.BTN_CONTRIB, contributions.contrib_entry, True),
            (mm.BTN_SETTINGS, settings.settings_entry, True),
        ]
        # Keep core financial/settings entry points covered
        results = {}
        for label, handler, needs_state in starters:
            msg = _message(label)
            msg.chat = MagicMock(type="private")
            await state.clear()
            if needs_state:
                await handler(msg, state, member)
            else:
                await handler(msg, member)
            assert msg.answer.await_count >= 1, label
            results[label] = "ok"
        assert len(results) == len(starters)

    async def test_deposit_fsm_summary_matches_journal(self, op_db):
        session = _session(op_db)
        try:
            real = _member(session)
            usd = session.query(Currency).filter_by(code="USD").one()
            usd_id = usd.id
            member = MagicMock()
            member.id = real.id
            member.is_ceo = real.is_ceo
            member.telegram_id = real.telegram_id
        finally:
            session.close()

        state = _fsm()
        from rawafed_bot.bot.handlers import deposit as dep

        msg = _message(mm.BTN_DEPOSIT)
        msg.chat = MagicMock(type="private")
        await dep.start_deposit(msg, state, member)
        assert await state.get_state() == DepositStates.choosing_currency.state

        cb = _callback(f"cur:{usd_id}")
        await dep.choose_currency(cb, state)
        assert await state.get_state() == DepositStates.entering_amount.state

        for amount_text in ("١٢٥.٥٠", "125.50"):
            await state.set_state(DepositStates.entering_amount)
            await state.update_data(currency_id=usd_id)
            msg_amt = _message(amount_text)
            await dep.enter_amount(msg_amt, state)
            data = await state.get_data()
            assert data["amount"] == 12550

        msg_desc = _message("إيداع تشغيلي")
        await dep.enter_description(msg_desc, state)
        assert await state.get_state() == DepositStates.confirming.state
        summary = msg_desc.answer.await_args.args[0]
        assert "125.50" in summary
        assert "إيداع تشغيلي" in summary

        cb_yes = _callback("cfm:deposit:yes")
        await dep.confirm_deposit(cb_yes, state, member)
        success = cb_yes.message.edit_text.await_args.args[0]
        assert "✅" in success
        assert "125.50" in success

        session = _session(op_db)
        try:
            tx = session.query(Transaction).order_by(Transaction.id.desc()).first()
            assert tx.amount == 12550
            assert tx.status == "active"
            entry = session.query(JournalEntry).filter_by(transaction_id=tx.id).one()
            lines = session.query(JournalLine).filter_by(journal_entry_id=entry.id).all()
            assert sum(l.debit for l in lines) == sum(l.credit for l in lines) == 12550
            cash = session.query(Account).filter_by(
                account_type="cash_box", currency_id=usd_id
            ).one()
            assert cash.balance == 12550
            usd = session.query(Currency).filter_by(id=usd_id).one()
            assert format_amount(tx.amount, usd) in success
            assert_stored_balances_match_ledger(session)
        finally:
            session.close()

    async def test_cancel_clears_fsm(self, op_db):
        from rawafed_bot.bot.handlers import common, deposit

        session = _session(op_db)
        try:
            real = _member(session)
            member = MagicMock()
            member.id = real.id
            member.is_ceo = real.is_ceo
            member.telegram_id = real.telegram_id
        finally:
            session.close()

        state = _fsm()
        msg = _message(mm.BTN_DEPOSIT)
        msg.chat = MagicMock(type="private")
        await deposit.start_deposit(msg, state, member)
        assert await state.get_state() is not None
        cancel = _message("إلغاء")
        await common.cmd_cancel(cancel, state)
        assert await state.get_state() is None

    async def test_fsm_isolation_two_users(self, op_db):
        from rawafed_bot.bot.handlers import deposit

        session = _session(op_db)
        try:
            m1 = _member(session, 111111111)
            m2 = _member(session, 222222222)
            mem1 = MagicMock(id=m1.id, is_ceo=m1.is_ceo, telegram_id=m1.telegram_id)
            mem2 = MagicMock(id=m2.id, is_ceo=m2.is_ceo, telegram_id=m2.telegram_id)
        finally:
            session.close()

        s1 = _fsm(111111111)
        s2 = _fsm(222222222)
        msg1 = _message(mm.BTN_DEPOSIT, 111111111)
        msg1.chat = MagicMock(type="private")
        msg2 = _message(mm.BTN_DEPOSIT, 222222222)
        msg2.chat = MagicMock(type="private")
        await deposit.start_deposit(msg1, s1, mem1)
        await deposit.start_deposit(msg2, s2, mem2)
        assert await s1.get_state() == DepositStates.choosing_currency.state
        assert await s2.get_state() == DepositStates.choosing_currency.state
        await s1.clear()
        assert await s1.get_state() is None
        assert await s2.get_state() == DepositStates.choosing_currency.state

    async def test_expense_mode_starts(self, op_db):
        from rawafed_bot.bot.handlers import expense

        session = _session(op_db)
        try:
            real = _member(session)
            member = MagicMock(
                id=real.id, is_ceo=real.is_ceo, telegram_id=real.telegram_id
            )
        finally:
            session.close()

        state = _fsm()
        msg = _message(mm.BTN_EXPENSE)
        msg.chat = MagicMock(type="private")
        await expense.start_expense(msg, state, member)
        assert await state.get_state() == ExpenseStates.choosing_mode.state


class TestMoneyAndCurrenciesOperational:
    def test_arabic_english_amounts_and_currencies(self, op_db):
        session = _session(op_db)
        try:
            usd = find_currency(session, "دولار")
            syp = find_currency(session, "SYP")
            try_c = find_currency(session, "ليرة تركية")
            assert usd.code == "USD"
            assert syp.code == "SYP"
            assert try_c.code == "TRY"
            assert parse_user_amount("1,000.00", usd) == 100000
            assert parse_user_amount("١٠٠", usd) == 10000
            assert parse_user_amount("500000", syp) == 50000000
        finally:
            session.close()


class TestReportsExcelOperational:
    def test_excel_matches_ledger(self, op_db, tmp_path, monkeypatch):
        session = _session(op_db)
        try:
            mem = _member(session)
            usd = session.query(Currency).filter_by(code="USD").one()
            OperationService.record_deposit(
                session, 77700, usd.id, mem.id, "ops", mem.id, "ops-xl-1"
            )
            OperationService.record_expense_from_box(
                session, 700, usd.id, 1, mem.id, "ops-e", mem.id, "ops-xl-2"
            )
            import rawafed_bot.reports.excel_export as ee
            monkeypatch.setattr(ee, "BASE_DIR", tmp_path)
            path = ReportGenerator.export_period_excel(session, title="تشغيلي")
            wb = load_workbook(path)
            cash_sheet = wb["الصندوق"]
            usd_val = None
            for row in cash_sheet.iter_rows(min_row=2, values_only=True):
                if row[0] == "USD":
                    usd_val = float(row[1])
            cash = session.query(Account).filter_by(
                account_type="cash_box", currency_id=usd.id
            ).one()
            assert abs(usd_val - cash.balance / 100) < 1e-9
            text = ReportService.cash_box_report(session)
            assert "USD" in text
            assert_stored_balances_match_ledger(session)
        finally:
            session.close()


class TestSchedulerOperational:
    def test_friday_mapping_and_jobs(self):
        assert _apscheduler_weekday(5) == 4  # Friday under APScheduler
        assert _apscheduler_weekday(0) == 6  # Sunday
        sched = create_scheduler(bot=None)
        jobs = {j.id: j for j in sched.get_jobs()}
        assert "weekly_report" in jobs
        assert "monthly_report" in jobs
        assert "overdue_contributions" in jobs
        z = ZoneInfo(settings.TIMEZONE)
        base = datetime(2026, 11, 9, 12, 0, tzinfo=z)
        nxt = jobs["weekly_report"].trigger.get_next_fire_time(None, base)
        assert nxt.strftime("%A") == "Friday"
        assert nxt.hour == settings.WEEKLY_REPORT_HOUR


class TestBackupRestoreOperational:
    def test_backup_restore_roundtrip(self, op_db, tmp_path, monkeypatch):
        db_path, Session = op_db
        session = Session()
        try:
            mem = _member(session)
            usd = session.query(Currency).filter_by(code="USD").one()
            OperationService.record_deposit(
                session, 5000, usd.id, mem.id, "bak", mem.id, "bak-1"
            )
        finally:
            session.close()

        import rawafed_bot.services.backup_service as bs
        monkeypatch.setattr(bs, "BASE_DIR", tmp_path)
        monkeypatch.setattr(bs.settings, "DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

        backup = BackupService.create_backup(note="ops")
        assert backup.exists()

        db_path.write_bytes(b"CORRUPT")
        BackupService.restore_backup(backup)
        engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        with engine.connect() as c:
            n = c.execute(text("select count(*) from transactions")).scalar()
            bal = c.execute(text(
                "select balance from accounts where account_type='cash_box' "
                "and currency_id=(select id from currencies where code='USD')"
            )).scalar()
        assert n >= 1
        assert bal == 5000
        engine.dispose()


class TestPersistenceAcrossRestart:
    def test_data_survives_reopen(self, tmp_path, monkeypatch):
        db_path = tmp_path / "persist.db"
        url = f"sqlite:///{db_path.as_posix()}"

        def open_session():
            eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
            configure_sqlite_engine(eng)
            Base.metadata.create_all(bind=eng)
            return eng, sessionmaker(bind=eng)()

        eng1, s1 = open_session()
        import rawafed_bot.database.connection as conn
        monkeypatch.setattr(conn, "SessionLocal", sessionmaker(bind=eng1))
        seed_all(s1)
        mem = s1.query(Member).first()
        usd = s1.query(Currency).filter_by(code="USD").one()
        usd_id = usd.id
        OperationService.record_deposit(
            s1, 4242, usd_id, mem.id, "persist", mem.id, "persist-1"
        )
        s1.close()
        eng1.dispose()

        eng2, s2 = open_session()
        bal = s2.query(Account).filter_by(
            account_type="cash_box", currency_id=usd_id
        ).one().balance
        txs = s2.query(Transaction).count()
        assert bal == 4242
        assert txs == 1
        assert_stored_balances_match_ledger(s2)
        s2.close()
        eng2.dispose()
