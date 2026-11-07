"""FadeHost deployment readiness — no polling, no production DB writes."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from rawafed_bot.bot.app import create_dispatcher
from rawafed_bot.bot.keyboards import main_menu as mm
from rawafed_bot.core.config import resolve_database_url, settings, sqlite_path_from_url
from rawafed_bot.core.version import CODE_BUILD_ID, MENU_VERSION


ROOT = Path(__file__).resolve().parents[2]


class TestEntryPoint:
    def test_main_py_is_real_bot_not_echo(self):
        text = (ROOT / "main.py").read_text(encoding="utf-8")
        assert "run_bot" in text
        assert "Echo" not in text or "not an Echo" in text
        assert "I am alive" not in text
        assert "Hi," not in text
        tree = ast.parse(text)
        assert any(
            isinstance(n, ast.If) and getattr(n.test, "left", None)
            for n in tree.body
        ) or '__main__' in text

    def test_no_echo_handler_in_project_handlers(self):
        handlers = ROOT / "rawafed_bot" / "bot" / "handlers"
        banned = ("I am alive", "Echo Bot", "echo_bot", "Hi, I am")
        hits = []
        for p in handlers.rglob("*.py"):
            body = p.read_text(encoding="utf-8")
            for b in banned:
                if b in body:
                    hits.append(f"{p.name}:{b}")
        assert hits == []


class TestMenuAndRouters:
    def test_menu_v5_loaded(self):
        assert MENU_VERSION.startswith("menu-v5-contrib-pocket")
        labels = {b.text for row in mm.main_menu_keyboard(is_ceo=True).keyboard for b in row}
        assert mm.BTN_ADVANCES not in labels
        assert mm.BTN_WITHDRAW in labels
        assert mm.BTN_CONTRIB_CREATE in labels
        assert mm.BTN_EXPORT == "📥 تصدير Excel"
        assert "📊 التقارير المالية" not in labels

    def test_all_routers_registered(self):
        dp = create_dispatcher()
        names = {r.name for r in dp.sub_routers}
        required = {
            "start", "group_setup", "group_ops", "group_chat", "guide", "common",
            "cashbox", "expense", "deposit", "withdrawal", "debts", "members",
            "history", "reports", "contributions", "roles_admin", "settings",
            "group_noise",
        }
        assert required <= names
        assert list(r.name for r in dp.sub_routers)[-1] == "group_noise"


class TestDbPathConfig:
    def test_db_path_env_resolves_absolute_linux_style(self):
        url = resolve_database_url(db_path="/data/rawafed.db", database_url="")
        assert url == "sqlite:////data/rawafed.db"
        # Raw SQLite path must stay POSIX absolute (FadeHost /data)
        assert url.replace("sqlite:///", "", 1) == "/data/rawafed.db"

    def test_database_url_fallback(self):
        url = resolve_database_url(db_path="", database_url="sqlite:///tmp/x.db")
        assert url == "sqlite:///tmp/x.db"

    def test_seed_does_not_wipe_existing_db(self, tmp_path, monkeypatch):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from rawafed_bot.database.connection import Base, configure_sqlite_engine
        from rawafed_bot.database.seeder import seed_all
        from rawafed_bot.database.models import Member, Transaction
        from rawafed_bot.database.models.currency import Currency
        from rawafed_bot.services.operation_service import OperationService

        db_file = tmp_path / "prod_like.db"
        url = f"sqlite:///{db_file.as_posix()}"
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
        configure_sqlite_engine(engine)
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)

        monkeypatch.setattr(settings, "DATABASE_URL", url)
        monkeypatch.setenv("ALLOW_ENV_MEMBER_BOOTSTRAP", "0")
        monkeypatch.setattr(settings, "CEO_TELEGRAM_ID", 111111111)

        import rawafed_bot.database.connection as conn
        monkeypatch.setattr(conn, "SessionLocal", Session)
        monkeypatch.setattr(conn, "engine", engine)

        with Session() as s:
            seed_all(s)
            ceo = s.query(Member).filter_by(is_ceo=True).one()
            usd = s.query(Currency).filter_by(code="USD").one()
            OperationService.record_deposit(
                s, 99900, usd.id, ceo.id, "keep-me", ceo.id, "fade-keep-1"
            )
            tx_count = s.query(Transaction).count()
            mem_count = s.query(Member).count()

        with Session() as s2:
            seed_all(s2)  # second boot — must not wipe
            assert s2.query(Transaction).count() == tx_count
            assert s2.query(Member).count() == mem_count
            assert s2.query(Transaction).filter_by(idempotency_key="fade-keep-1").count() == 1

        engine.dispose()


class TestBuildIdentity:
    def test_code_build_id_stable(self):
        assert CODE_BUILD_ID.startswith("2.1.0+")
        assert settings.effective_build_id
