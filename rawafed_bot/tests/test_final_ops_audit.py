"""Final operational audit — isolated temp DB, no production, no live Telegram."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rawafed_bot.accounting.ledger import assert_stored_balances_match_ledger
from rawafed_bot.bot.app import create_dispatcher
from rawafed_bot.bot.handlers import group_ops
from rawafed_bot.bot.keyboards import main_menu as mm
from rawafed_bot.bot.states import GroupOpStates
from rawafed_bot.core.config import settings
from rawafed_bot.database.connection import Base, configure_sqlite_engine
from rawafed_bot.database.models import Account, JournalEntry, JournalLine, Member, Transaction
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.expense_category import ExpenseCategory
from rawafed_bot.database.models.role import Role
from rawafed_bot.database.models.role_transfer import RoleTransferRequest
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.reports.generator import ReportGenerator
from rawafed_bot.scheduler.jobs import create_scheduler
from rawafed_bot.services.intent_router import IntentRouter
from rawafed_bot.services.nl_operation_parser import NLOperationParser
from rawafed_bot.services.operation_service import OperationError, OperationService
from rawafed_bot.services.permission_service import PermissionService
from rawafed_bot.services.registration_service import RegistrationService
from rawafed_bot.services.role_transfer_service import RoleTransferService
from rawafed_bot.utils.money import find_currency, format_amount, parse_user_amount


@pytest.fixture
def audit_db(tmp_path, monkeypatch):
    """Dedicated temporary SQLite — never production rawafed.db."""
    db_path = tmp_path / "final_audit.db"
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
    yield db_path, Session
    engine.dispose()
    assert "rawafed.db" not in str(db_path)


def _sess(audit_db):
    return audit_db[1]()


def _shared_storage_fsm(storage, user_id, chat_id=-10099):
    return FSMContext(
        storage=storage,
        key=StorageKey(bot_id=1, chat_id=chat_id, user_id=user_id),
    )


class TestDispatcherAndNoPrivate:
    def test_routers_include_noise_last(self):
        dp = create_dispatcher()
        names = [r.name for r in dp.sub_routers]
        assert names[-1] == "group_noise"
        assert "group_ops" in names and "guide" in names
        assert len(names) == len(set(names))

    def test_no_private_redirect_strings_in_handlers(self):
        root = Path(__file__).resolve().parents[1] / "bot" / "handlers"
        banned = ("افتح محادثة خاصة", "افتح محادثتك الخاصة")
        hits = []
        for p in root.glob("*.py"):
            text = p.read_text(encoding="utf-8")
            for b in banned:
                if b in text:
                    hits.append(f"{p.name}:{b}")
        assert hits == []

    def test_scheduler_jobs_unique_ids(self):
        s1 = create_scheduler(bot=None)
        ids = [j.id for j in s1.get_jobs()]
        assert len(ids) == len(set(ids))
        assert set(ids) >= {"weekly_report", "monthly_report", "overdue_contributions"}
        # Do not start/shutdown — AsyncIOScheduler needs a running loop

    def test_polling_lock_blocks_second_holder(self, tmp_path, monkeypatch):
        import json

        import rawafed_bot.bot.polling_lock as pl

        lock = tmp_path / "bot_polling_test.lock"
        monkeypatch.setattr(pl, "lock_path", lambda: lock)
        monkeypatch.setattr(pl, "_held", False)
        monkeypatch.setattr(pl, "_lock_path", None)
        pl.acquire_polling_lock()
        assert lock.exists()
        data = json.loads(lock.read_text(encoding="utf-8"))
        owner_pid = data["pid"]
        monkeypatch.setattr(pl, "_held", False)
        monkeypatch.setattr(pl, "_lock_path", None)
        monkeypatch.setattr(pl.os, "getpid", lambda: 9_999_999)
        monkeypatch.setattr(pl, "_pid_alive", lambda pid: True)
        with pytest.raises(RuntimeError, match="Polling already running"):
            pl.acquire_polling_lock()
        monkeypatch.setattr(pl.os, "getpid", lambda: owner_pid)
        monkeypatch.setattr(pl, "_held", True)
        monkeypatch.setattr(pl, "_lock_path", lock)
        pl.release_polling_lock()
        assert not lock.exists()


class TestCurrenciesIndependence:
    def test_three_currencies_independent_ledger(self, audit_db):
        db = _sess(audit_db)
        try:
            mem = db.query(Member).filter_by(is_ceo=True).one()
            usd = db.query(Currency).filter_by(code="USD").one()
            syp = db.query(Currency).filter_by(code="SYP").one()
            try_c = db.query(Currency).filter_by(code="TRY").one()
            OperationService.record_deposit(db, 10000, usd.id, mem.id, "u", mem.id, "a-u1")
            OperationService.record_deposit(db, 500000, syp.id, mem.id, "s", mem.id, "a-s1")
            OperationService.record_deposit(db, 20000, try_c.id, mem.id, "t", mem.id, "a-t1")
            cat = db.query(ExpenseCategory).first()
            OperationService.record_expense_from_box(
                db, 2500, usd.id, cat.id, mem.id, "eu", mem.id, "a-ue1"
            )
            cash_usd = db.query(Account).filter_by(account_type="cash_box", currency_id=usd.id).one()
            cash_syp = db.query(Account).filter_by(account_type="cash_box", currency_id=syp.id).one()
            cash_try = db.query(Account).filter_by(account_type="cash_box", currency_id=try_c.id).one()
            assert cash_usd.balance == 7500
            assert cash_syp.balance == 500000
            assert cash_try.balance == 20000
            assert_stored_balances_match_ledger(db)
        finally:
            db.close()


class TestMoneyParsing:
    def test_arabic_english_fractions(self, audit_db):
        db = _sess(audit_db)
        try:
            usd = find_currency(db, "دولار")
            assert parse_user_amount("١٢٥.٥٠", usd) == 12550
            assert parse_user_amount("125.50", usd) == 12550
            assert parse_user_amount("1,000.25", usd) == 100025
            syp = find_currency(db, "ليرة سورية")
            assert parse_user_amount("٥٠", syp) == 5000
        finally:
            db.close()


class TestIdempotencyAndConfirmGuard:
    def test_duplicate_idempotency_rejected(self, audit_db):
        db = _sess(audit_db)
        try:
            mem = db.query(Member).filter_by(is_ceo=True).one()
            usd = db.query(Currency).filter_by(code="USD").one()
            OperationService.record_deposit(db, 1000, usd.id, mem.id, "x", mem.id, "idem-dup-1")
            with pytest.raises(OperationError):
                OperationService.record_deposit(db, 1000, usd.id, mem.id, "x", mem.id, "idem-dup-1")
            assert db.query(Transaction).filter_by(idempotency_key="idem-dup-1").count() == 1
            assert_stored_balances_match_ledger(db)
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_other_member_cannot_confirm(self, audit_db):
        db = _sess(audit_db)
        try:
            owner = db.query(Member).filter_by(telegram_id=settings.MEMBER_TELEGRAM_IDS[0]).one()
            other = db.query(Member).filter_by(telegram_id=settings.MEMBER_TELEGRAM_IDS[1]).one()
            owner_id = owner.id
            other_tg = other.telegram_id
            owner_tg = owner.telegram_id
            tx_before = db.query(Transaction).count()
        finally:
            db.close()

        storage = MemoryStorage()
        # Attacker's FSM carries a forged copy of the pending op (worst case)
        state = _shared_storage_fsm(storage, other_tg)
        await state.set_state(GroupOpStates.confirming)
        await state.update_data(gop={
            "token": "abcd1234",
            "owner_tg_id": owner_tg,
            "owner_member_id": owner_id,
            "source_message_id": 1,
            "op_type": "deposit",
            "amount_minor": 1000,
            "currency_id": 1,
            "description": "t",
            "confirmed": False,
        })
        cb = MagicMock()
        cb.data = "gop:yes:abcd1234"
        cb.from_user = MagicMock(id=other_tg)
        cb.answer = AsyncMock()
        cb.message = MagicMock()
        cb.message.edit_text = AsyncMock()
        await group_ops.confirm_group_op(cb, state, member=None, bot=MagicMock())
        msg = cb.answer.await_args.args[0]
        assert "عضو آخر" in msg
        data = await state.get_data()
        assert data["gop"]["confirmed"] is False

        db2 = _sess(audit_db)
        try:
            assert db2.query(Transaction).count() == tx_before
        finally:
            db2.close()

    @pytest.mark.asyncio
    async def test_double_confirm_blocked_by_flag(self, audit_db):
        owner_tg = settings.MEMBER_TELEGRAM_IDS[0]
        storage = MemoryStorage()
        state = _shared_storage_fsm(storage, owner_tg)
        await state.set_state(GroupOpStates.confirming)
        await state.update_data(gop={
            "token": "zzzz9999",
            "owner_tg_id": owner_tg,
            "owner_member_id": 1,
            "source_message_id": 9,
            "op_type": "deposit",
            "amount_minor": 100,
            "currency_id": 1,
            "description": "dup",
            "confirmed": True,
        })
        cb = MagicMock()
        cb.data = "gop:yes:zzzz9999"
        cb.from_user = MagicMock(id=owner_tg)
        cb.answer = AsyncMock()
        cb.message = MagicMock()
        await group_ops.confirm_group_op(cb, state, member=None, bot=MagicMock())
        assert "مسبقاً" in cb.answer.await_args.args[0]


class TestSessionIsolation:
    @pytest.mark.asyncio
    async def test_five_members_fsm_isolated(self):
        storage = MemoryStorage()
        states = [
            _shared_storage_fsm(storage, tid) for tid in settings.MEMBER_TELEGRAM_IDS
        ]
        assert len(states) == 5
        for i, st in enumerate(states):
            await st.set_state(GroupOpStates.collecting)
            await st.update_data(gop={
                "token": f"t{i}",
                "owner_tg_id": settings.MEMBER_TELEGRAM_IDS[i],
            })
        await states[0].clear()
        assert await states[0].get_state() is None
        for i, st in enumerate(states[1:], start=1):
            assert await st.get_state() == GroupOpStates.collecting.state
            assert (await st.get_data())["gop"]["token"] == f"t{i}"


class TestRoleTransferAudit:
    def test_unique_transfer_ceo_approve(self, audit_db):
        db = _sess(audit_db)
        try:
            for m in db.query(Member).filter(Member.is_ceo == False).all():
                m.is_active = False
                db.add(m)
            db.commit()
            RoleTransferService.ensure_extra_roles(db)
            a = RegistrationService.register_self(db, 770000001, "a", "A")
            b = RegistrationService.register_self(db, 770000002, "b", "B")
            ceo = db.query(Member).filter_by(is_ceo=True).one()
            acc = db.query(Role).filter_by(code="accountant").one()
            PermissionService.assign_role(db, a.id, acc.id, ceo.id)
            note = RoleTransferService.maybe_request_on_title(db, b, "accountant")
            assert note and "مشغول" in note
            req = db.query(RoleTransferRequest).filter_by(status="pending").one()
            RoleTransferService.approve(db, req.id, ceo)
            holders = RoleTransferService.holders(db, acc.id)
            assert len(holders) == 1 and holders[0].id == b.id
            assert ceo.is_ceo is True
        finally:
            db.close()


class TestPersistenceRestart:
    def test_data_survives_reopen(self, audit_db):
        path, Session = audit_db
        s = Session()
        try:
            mem = s.query(Member).filter_by(is_ceo=True).one()
            usd = s.query(Currency).filter_by(code="USD").one()
            OperationService.record_deposit(s, 33300, usd.id, mem.id, "persist", mem.id, "pers-1")
            mid = mem.id
            usd_id = usd.id
            bal = s.query(Account).filter_by(
                account_type="cash_box", currency_id=usd_id
            ).one().balance
        finally:
            s.close()
        s2 = Session()
        try:
            assert s2.query(Transaction).filter_by(idempotency_key="pers-1").count() == 1
            assert s2.query(Account).filter_by(
                account_type="cash_box", currency_id=usd_id
            ).one().balance == bal
            assert_stored_balances_match_ledger(s2)
            assert s2.query(Member).filter_by(id=mid).one().is_active is True
        finally:
            s2.close()


class TestReportsExcelLedger:
    def test_excel_matches_cash_ledger(self, audit_db, tmp_path, monkeypatch):
        db = _sess(audit_db)
        try:
            mem = db.query(Member).filter_by(is_ceo=True).one()
            usd = db.query(Currency).filter_by(code="USD").one()
            OperationService.record_deposit(db, 77700, usd.id, mem.id, "xl", mem.id, "xl-1")
            import rawafed_bot.reports.excel_export as ee

            monkeypatch.setattr(ee, "BASE_DIR", tmp_path)
            path = ReportGenerator.export_period_excel(db, title="audit")
            wb = load_workbook(path)
            cash_sheet = wb["الصندوق"]
            usd_val = None
            for row in cash_sheet.iter_rows(min_row=2, values_only=True):
                if row[0] == "USD":
                    usd_val = float(row[1])
            cash = db.query(Account).filter_by(account_type="cash_box", currency_id=usd.id).one()
            assert usd_val is not None
            assert abs(usd_val - cash.balance / 100) < 1e-9
            assert_stored_balances_match_ledger(db)
            tx = db.query(Transaction).filter_by(idempotency_key="xl-1").one()
            entry = db.query(JournalEntry).filter_by(transaction_id=tx.id).one()
            lines = db.query(JournalLine).filter_by(journal_entry_id=entry.id).all()
            assert sum(l.debit for l in lines) == sum(l.credit for l in lines) == 77700
        finally:
            db.close()


class TestNLThroughOperationService:
    def test_group_nl_expense_uses_operation_service(self, audit_db):
        db = _sess(audit_db)
        try:
            mem = db.query(Member).filter_by(is_ceo=True).one()
            p = NLOperationParser.parse(db, "يا محاسب سجل 10 دولار مصروف مواصلات")
            assert p.op_type == "expense" and not p.missing
            OperationService.record_deposit(
                db, 5000, p.currency_id, mem.id, "fund", mem.id, "nl-fund"
            )
            before = db.query(Transaction).count()
            tx = OperationService.record_expense_from_box(
                db, p.amount_minor, p.currency_id, p.category_id,
                mem.id, p.description or "مواصلات", mem.id, "nl-svc-1",
            )
            assert db.query(Transaction).count() == before + 1
            assert db.query(JournalEntry).filter_by(transaction_id=tx.id).count() == 1
            assert_stored_balances_match_ledger(db)
            r = IntentRouter.route(db, mem, "يا محاسب كم رصيد الصندوق بالدولار", "CEO")
            assert r.intent == "cashbox"
            assert "4" in r.reply or "USD" in r.reply or "دولار" in r.reply
            cash = db.query(Account).filter_by(
                account_type="cash_box", currency_id=p.currency_id
            ).one()
            cur = db.query(Currency).filter_by(id=p.currency_id).one()
            assert format_amount(cash.balance, cur) in r.reply
        finally:
            db.close()


class TestGuideAndMenu:
    def test_guide_pages_and_menu(self):
        from rawafed_bot.bot.handlers.guide import PAGES

        assert "expense" in PAGES and "faq" in PAGES
        assert "لا — كل التدفقات العادية داخل المجموعة" in PAGES["faq"][0]
        kb = mm.main_menu_keyboard()
        labels = {b.text for row in kb.keyboard for b in row}
        assert mm.BTN_GUIDE in labels
        assert mm.BTN_MAIN in labels
