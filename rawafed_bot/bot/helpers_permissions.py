"""Permission gate helpers for handlers."""
from __future__ import annotations

from aiogram.types import Message

from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.permission_service import PermissionErrorDenied, PermissionService


async def ensure_perm(message: Message, member: Member, code: str) -> bool:
    # Read identity from instance dict to survive detached/expired members
    raw = getattr(member, "__dict__", {}) or {}
    mid = raw.get("id")
    tid = raw.get("telegram_id")
    with get_db_context() as db:
        m = None
        if mid is not None:
            m = db.query(Member).filter_by(id=mid).first()
        if m is None and tid is not None:
            m = db.query(Member).filter_by(telegram_id=tid).first()
        if not m:
            await message.answer("⚠️ العضو غير موجود.")
            return False
        try:
            PermissionService.require(db, m, code)
            return True
        except PermissionErrorDenied as exc:
            await message.answer(str(exc))
            return False


async def require_private_chat(message: Message, action_ar: str) -> bool:
    """Deprecated: group-first mode — always allow in-group flows."""
    return True
