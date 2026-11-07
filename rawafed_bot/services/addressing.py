"""Detect whether a group message is addressed to RAWAFED BOT / المحاسب."""
from __future__ import annotations

import re
from typing import Optional

from aiogram.types import Message, User

# Addressing that clearly targets the bot
_ADDRESS_PREFIX = re.compile(
    r"^\s*(?:يا\s+)?محاسب(?:\s*[,،:]|\s+|$)",
    re.UNICODE,
)
# Soft: "محاسب،" / "محاسب؟" mid-start patterns
_ADDRESS_SOFT = re.compile(
    r"(?:^|[\s،,])يا\s+محاسب(?:\s|[,،:]|$)|(?:^|[\s،,])محاسب\s*[,،:؟?]",
    re.UNICODE,
)
# Casual mention of accountant without address — ignore alone
_BARE_WORD = re.compile(r"محاسب", re.UNICODE)


def _bot_usernames(bot_user: Optional[User]) -> set[str]:
    if not bot_user or not bot_user.username:
        return set()
    return {f"@{bot_user.username}".lower(), bot_user.username.lower()}


def is_bot_message(message: Message, bot_id: int = None) -> bool:
    """True if the sender is the bot itself (prevent reply loops)."""
    user = message.from_user
    if not user:
        return True
    if user.is_bot:
        return True
    if bot_id is not None and user.id == bot_id:
        return True
    return False


def is_addressed_to_accountant(
    message: Message,
    bot_user: Optional[User] = None,
) -> bool:
    """Return True only when the message is clearly directed at the bot."""
    if is_bot_message(message):
        return False
    text = (message.text or message.caption or "").strip()
    if not text:
        return False

    # Reply to a bot message
    reply = message.reply_to_message
    if reply and reply.from_user and reply.from_user.is_bot:
        return True

    # Explicit @bot mention / text_mention of bot
    usernames = _bot_usernames(bot_user)
    entities = list(message.entities or []) + list(message.caption_entities or [])
    for ent in entities:
        if ent.type == "mention":
            frag = text[ent.offset : ent.offset + ent.length].lower()
            if frag in usernames:
                return True
        if ent.type == "text_mention" and ent.user and ent.user.is_bot:
            return True
        if ent.type == "bot_command":
            # /command@bot in groups
            return True

    for uname in usernames:
        if uname and uname in text.lower():
            return True

    # Vocative accountant address
    if _ADDRESS_PREFIX.search(text):
        return True
    if _ADDRESS_SOFT.search(text):
        return True

    return False


def strip_address_prefix(text: str) -> str:
    """Remove leading يا محاسب / محاسب، for intent parsing."""
    raw = (text or "").strip()
    raw = re.sub(r"^@\w+\s*", "", raw)
    raw = _ADDRESS_PREFIX.sub("", raw, count=1).strip()
    raw = re.sub(r"^[,،:\-–]+\s*", "", raw).strip()
    return raw
