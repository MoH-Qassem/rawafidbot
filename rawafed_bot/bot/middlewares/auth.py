"""Auth middleware: allow setup/registration/group intelligence; require membership for finance."""
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from rawafed_bot.database.connection import get_db_context
from rawafed_bot.services.auth_service import AuthService


_ACCOUNTANT_HINT = re.compile(
    r"(?:^|[\s،,])(?:يا\s+)?محاسب(?:\s|[,،:؟?]|$)|@\w+",
    re.UNICODE,
)


def _is_public_event(event: TelegramObject) -> bool:
    """Events allowed before / without full membership registration."""
    if isinstance(event, Message):
        text = (event.text or "").strip()
        if text.startswith(("/setup", "/start", "/status", "/profile", "/cancel", "/me")):
            return True
        if text in {"إلغاء", "الغاء"}:
            return True
        # Group onboarding + accountant addressing must reach handlers
        if event.chat and event.chat.type in {"group", "supergroup"}:
            return True
        # Private: custom title while onboarding
        if _ACCOUNTANT_HINT.search(text):
            return True
        return False
    if isinstance(event, CallbackQuery):
        data = event.data or ""
        return data.startswith(("reg:", "setup:", "cfm:reg", "job:", "prof:", "gop:", "guide:", "rtr:"))
    return False


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        public = _is_public_event(event)

        with get_db_context() as db:
            known = AuthService.is_known_user(db, user.id)
            member = AuthService.get_member_by_telegram_id(db, user.id)

            if public:
                if AuthService.is_ceo(user.id):
                    try:
                        member = AuthService.require_member(db, user.id)
                        from rawafed_bot.database.seeder import seed_accounts
                        seed_accounts(db)
                        db.expunge(member)
                        data["member"] = member
                    except PermissionError:
                        data["member"] = None
                elif member and member.is_active:
                    db.expunge(member)
                    data["member"] = member
                else:
                    data["member"] = None

                # Group menu taps from unregistered users must not reach finance handlers
                if (
                    isinstance(event, Message)
                    and event.text
                    and not (data.get("member") and data["member"].is_active)
                ):
                    from rawafed_bot.bot.keyboards.main_menu import (
                        BTN_GUIDE,
                        BTN_MAIN,
                        all_ceo_buttons,
                        texts_for,
                    )
                    finance_texts: set[str] = set()
                    for btn in all_ceo_buttons():
                        if btn in {BTN_GUIDE, BTN_MAIN}:
                            continue
                        finance_texts |= texts_for(btn)
                    if event.text.strip() in finance_texts:
                        tip = (
                            "⚠️ لست مسجّلاً بعد.\n"
                            "أرسل /start داخل المجموعة لإكمال التسجيل، "
                            "أو اضغط «تسجيل عضويتي» بعد /setup."
                        )
                        await event.answer(tip)
                        return None

                return await handler(event, data)

            if not known and not (member and member.is_active):
                text = (
                    "⚠️ أنت غير مسجّل في نظام روافد.\n"
                    "في المجموعة سيظهر لك طلب التعرف عند أول تواصل، "
                    "أو اضغط «تسجيل عضويتي» بعد /setup."
                )
                if isinstance(event, Message):
                    await event.answer(text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
                return None

            try:
                member = AuthService.require_member(db, user.id)
                from rawafed_bot.database.seeder import seed_accounts
                seed_accounts(db)
            except PermissionError as exc:
                text = str(exc)
                if isinstance(event, Message):
                    await event.answer(text)
                elif isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
                return None
            db.expunge(member)
            data["member"] = member

        return await handler(event, data)
