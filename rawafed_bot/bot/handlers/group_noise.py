"""Acknowledge leftover group updates so aiogram does not warn 'Update is not handled'.

Runs last. Does not reply. Does not catch exceptions from earlier routers —
those already finished (or failed and propagated) before this handler runs.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

logger = logging.getLogger(__name__)
router = Router(name="group_noise")


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def acknowledge_leftover_group_update(message: Message) -> None:
    # Reached only if no earlier router handled the update.
    uid = message.from_user.id if message.from_user else None
    kind = "text" if message.text else (
        "photo" if message.photo else (
            "sticker" if message.sticker else (
                "document" if message.document else "other"
            )
        )
    )
    logger.debug(
        "group_noise: leftover group update ignored chat=%s user=%s kind=%s",
        message.chat.id,
        uid,
        kind,
    )
