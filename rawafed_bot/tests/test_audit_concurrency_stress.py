"""Idempotency, concurrency, and 1000-op stress audit."""
from __future__ import annotations

import random
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rawafed_bot.accounting.ledger import (
    assert_all_entries_balanced,
    assert_stored_balances_match_ledger,
)
from rawafed_bot.database.connection import Base, configure_sqlite_engine
from rawafed_bot.database.seeder import seed_all
from rawafed_bot.database.models.account import Account
from rawafed_bot.database.models.debt import MemberDebt
from rawafed_bot.database.models.transaction import Transaction
from rawafed_bot.services.operation_service import OperationError, OperationService
from rawafed_bot.tests.audit_helpers import cash, cat_id, currency_by_code, m, members


class TestIdempotencyConcurrency:
    def test_same_key_twice_single_effect(self, db):
        seed_all(db)
        mem = members(db)[0]
        cur = currency_by_code(db, "USD")
        key = "stress-idem-1"
        OperationService.record_deposit(db, m(100, "USD", db), cur.id, mem.id, "d", mem.id, key)
        with pytest.raises(OperationError):
            OperationService.record_deposit(db, m(100, "USD", db), cur.id, mem.id, "d", mem.id, key)
        assert cash(db, "USD").balance == m(100, "USD", db)
        assert db.query(Transaction).filter_by(idempotency_key=key).count() == 1

    def test_parallel_deposits_same_key(self, tmp_path):
        db_file = tmp_path / "concurrent.db"
        url = f"sqlite:///{db_file.as_posix()}"
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
        )
        configure_sqlite_engine(engine)

        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        setup = Session()
        seed_all(setup)
        mem = setup.query(Account).filter_by(account_type="member_equity").first().member
        cur_id = setup.query(Account).filter_by(account_type="cash_box").first().currency_id
        # Resolve minor units with seeded currency decimal places
        from rawafed_bot.database.models.currency import Currency
        dec = setup.query(Currency).filter_by(id=cur_id).one().decimal_places
        amount = int(round(25 * (10 ** dec)))
        setup.close()

        key = "parallel-same-key"
        results = {"ok": 0, "dup": 0, "err": 0}
        lock = threading.Lock()

        def worker():
            s = Session()
            try:
                OperationService.record_deposit(
                    s, amount, cur_id, mem.id, "parallel", mem.id, key
                )
                with lock:
                    results["ok"] += 1
            except OperationError:
                with lock:
                    results["dup"] += 1
            except Exception:
                with lock:
                    results["err"] += 1
            finally:
                s.close()

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        verify = Session()
        cash_box = verify.query(Account).filter_by(account_type="cash_box", currency_id=cur_id).one()
        tx_count = verify.query(Transaction).filter_by(idempotency_key=key).count()
        verify.close()
        engine.dispose()

        assert results["ok"] == 1
        assert results["dup"] >= 1
        assert results["err"] == 0
        assert tx_count == 1
        assert cash_box.balance == amount

    def test_parallel_distinct_deposits(self, tmp_path):
        db_file = tmp_path / "parallel_distinct.db"
        url = f"sqlite:///{db_file.as_posix()}"
        engine = create_engine(
            url, connect_args={"check_same_thread": False, "timeout": 30}
        )
        configure_sqlite_engine(engine)

        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        setup = Session()
        seed_all(setup)
        mem = setup.query(Account).filter_by(account_type="member_equity").first().member
        cur_id = setup.query(Account).filter_by(account_type="cash_box").first().currency_id
        from rawafed_bot.database.models.currency import Currency
        dec = setup.query(Currency).filter_by(id=cur_id).one().decimal_places
        unit = 10 ** dec
        setup.close()

        def worker(i):
            s = Session()
            try:
                OperationService.record_deposit(
                    s, 10 * unit, cur_id, mem.id, f"p{i}", mem.id, f"distinct-{i}-{uuid.uuid4().hex}"
                )
                return True
            finally:
                s.close()

        with ThreadPoolExecutor(max_workers=5) as pool:
            futs = [pool.submit(worker, i) for i in range(5)]
            assert all(f.result() for f in as_completed(futs))

        verify = Session()
        bal = verify.query(Account).filter_by(account_type="cash_box", currency_id=cur_id).one().balance
        assert bal == 50 * unit
        assert_all_entries_balanced(verify)
        assert_stored_balances_match_ledger(verify)
        verify.close()
        engine.dispose()


class TestStressLedgerRebuild:
    def test_1000_random_operations_ledger_matches(self, db):
        seed_all(db)
        rng = random.Random(20261107)
        ms = members(db)
        codes = ["USD", "SYP", "TRY"]
        cid = cat_id(db)

        # Seed cash so expenses/withdrawals can succeed
        for code in codes:
            cur = currency_by_code(db, code)
            for mem in ms[:2]:
                OperationService.record_deposit(
                    db, m(50000, code, db), cur.id, mem.id, f"seed-{code}-{mem.id}",
                    mem.id, f"stress-seed-{code}-{mem.id}",
                )

        ops_ok = 0
        for i in range(1000):
            mem = rng.choice(ms)
            code = rng.choice(codes)
            cur = currency_by_code(db, code)
            kind = rng.choice([
                "deposit", "deposit", "expense", "personal", "withdraw",
                "advance", "repay",
            ])
            amount_major = rng.choice([1, 5, 10, 25, 50, 100, "0.01", "0.50", 3])
            amount = m(amount_major, code, db)
            key = f"stress-{i}-{uuid.uuid4().hex[:8]}"
            try:
                if kind == "deposit":
                    OperationService.record_deposit(
                        db, amount, cur.id, mem.id, f"s{i}", mem.id, key
                    )
                elif kind == "expense":
                    OperationService.record_expense_from_box(
                        db, amount, cur.id, cid, mem.id, f"s{i}", mem.id, key
                    )
                elif kind == "personal":
                    OperationService.record_personal_expense(
                        db, amount, cur.id, cid, mem.id, f"s{i}", mem.id, key
                    )
                elif kind == "withdraw":
                    OperationService.record_withdrawal(
                        db, amount, cur.id, mem.id, f"s{i}", mem.id, key
                    )
                elif kind == "advance":
                    OperationService.record_withdrawal_as_advance(
                        db, amount, cur.id, mem.id, f"s{i}", "stress", mem.id, key
                    )
                elif kind == "repay":
                    debt = (
                        db.query(MemberDebt)
                        .filter_by(member_id=mem.id, currency_id=cur.id, status="active")
                        .filter(MemberDebt.remaining > 0)
                        .first()
                    )
                    if not debt:
                        continue
                    pay = min(amount, debt.remaining)
                    OperationService.record_debt_repayment(
                        db, pay, cur.id, mem.id, f"s{i}", mem.id, debt.id, key
                    )
                ops_ok += 1
            except (OperationError, Exception):
                # Expected when cash insufficient etc.; must leave ledger consistent
                pass

            if i % 100 == 0:
                assert_all_entries_balanced(db)
                assert_stored_balances_match_ledger(db)

        assert ops_ok > 100
        assert_all_entries_balanced(db)
        assert_stored_balances_match_ledger(db)
        # No duplicate idempotency keys among transactions
        keys = [t.idempotency_key for t in db.query(Transaction).all() if t.idempotency_key]
        assert len(keys) == len(set(keys))
