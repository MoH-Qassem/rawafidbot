"""Filters for group intelligence without swallowing unrelated updates."""
from __future__ import annotations

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.filters import BaseFilter
from aiogram.types import Message

from rawafed_bot.database.connection import get_db_context
from rawafed_bot.services.addressing import is_addressed_to_accountant, is_bot_message
from rawafed_bot.services.onboarding_service import OnboardingService


class GroupIntelligenceFilter(BaseFilter):
    """Match group texts that need onboarding or accountant reply only."""

    async def __call__(self, message: Message, bot: Bot) -> bool:
        if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            return False
        if not message.text:
            return False
        # Let /start /setup /status… reach their dedicated routers
        if message.text.lstrip().startswith("/"):
            return False
        if not message.from_user or is_bot_message(message, bot.id):
            return False

        with get_db_context() as db:
            registered = OnboardingService.is_registered(db, message.from_user.id)

        if not registered:
            # First-contact / invite follow-up (handler decides spam rules)
            return True

        me = await bot.me()
        return is_addressed_to_accountant(message, me)
