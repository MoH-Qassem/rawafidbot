"""Regression: auth must release SQLite before awaiting handlers."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, Message, User
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rawafed_bot.bot.middlewares.auth import AuthMiddleware
from rawafed_bot.database.connection import Base, configure_sqlite_engine, get_db_context
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.seeder import seed_all


@pytest.fixture()
def lock_db(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'lock.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 5})
    configure_sqlite_engine(engine)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    import rawafed_bot.database.connection as conn

    monkeypatch.setattr(conn, "SessionLocal", Session)
    monkeypatch.setattr(conn, "engine", engine)
    monkeypatch.setattr(conn.settings, "DATABASE_URL", url)
    monkeypatch.setattr(conn.settings, "CEO_TELEGRAM_ID", 111111111)

    with Session() as session:
        seed_all(session)
        m = session.query(Member).filter_by(telegram_id=111111111).first()
        if m is None:
            m = Member(
                telegram_id=111111111,
                display_name="CEO",
                is_ceo=True,
                is_active=True,
                profile_completed=True,
            )
            session.add(m)
            session.commit()
    yield
    engine.dispose()


def test_handler_can_open_db_after_auth(lock_db):
    """Old bug: public path awaited handler inside get_db_context → database is locked."""
    mw = AuthMiddleware()
    seen = {}

    async def handler(event, data):
        with get_db_context() as db:
            seen["count"] = db.query(Member).count()
            seen["member_id"] = data["member"].id if data.get("member") else None
        return "ok"

    user = User(id=111111111, is_bot=False, first_name="CEO")
    chat = Chat(id=111111111, type="private")
    message = Message(
        message_id=1,
        date=0,
        chat=chat,
        from_user=user,
        text="/start",
    )

    result = asyncio.get_event_loop().run_until_complete(
        mw(handler, message, {"event_from_user": user})
    )
    assert result == "ok"
    assert seen["count"] >= 1
    assert seen["member_id"] is not None
