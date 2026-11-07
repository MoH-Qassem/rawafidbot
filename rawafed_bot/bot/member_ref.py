"""Safe access to detached Member identity fields."""
from __future__ import annotations

from typing import Optional, Tuple

from rawafed_bot.database.models.member import Member


def member_ids(member: Optional[Member]) -> Tuple[Optional[int], Optional[int]]:
    """Return (id, telegram_id) without triggering SQLAlchemy refresh."""
    if member is None:
        return None, None
    raw = getattr(member, "__dict__", {}) or {}
    return raw.get("id"), raw.get("telegram_id")


def member_is_ceo(member: Optional[Member]) -> bool:
    if member is None:
        return False
    raw = getattr(member, "__dict__", {}) or {}
    if "is_ceo" in raw:
        return bool(raw.get("is_ceo"))
    return bool(getattr(member, "is_ceo", False))
