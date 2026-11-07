"""Canonical /start handler — activates MENU_VERSION reply keyboard."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from rawafed_bot.bot.keyboards.main_menu import main_menu_keyboard
from rawafed_bot.bot.states import OnboardingStates
from rawafed_bot.core.config import settings
from rawafed_bot.core.version import (
    BUILD_ID,
    MENU_VERSION,
    START_HANDLER,
    WELCOME_REGISTERED,
    WELCOME_UNREGISTERED,
)
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.onboarding_service import JOB_TITLE_PRESETS, OnboardingService
from rawafed_bot.services.registration_service import RegistrationService
from rawafed_bot.utils.callbacks import JOB, pack

logger = logging.getLogger(__name__)
router = Router(name="start")


def _job_keyboard():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [
        [InlineKeyboardButton(text=label, callback_data=pack(JOB, code))]
        for code, label in JOB_TITLE_PRESETS
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _profile_incomplete(member: Member) -> bool:
    """Incomplete only when neither display nor telegram name is set."""
    display = (getattr(member, "display_name", None) or "").strip()
    tg_name = (getattr(member, "telegram_full_name", None) or "").strip()
    return not display and not tg_name


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, member: Member = None):
    """Activate the current UI build. Clears any dangling FSM."""
    await state.clear()
    logger.info(
        "cmd_start handler=%s menu=%s build=%s user=%s chat=%s registered=%s",
        START_HANDLER,
        MENU_VERSION,
        BUILD_ID,
        message.from_user.id if message.from_user else None,
        message.chat.id if message.chat else None,
        bool(member and member.is_active),
    )

    if member is None or not member.is_active:
        await _start_unregistered(message, state)
        return

    if _profile_incomplete(member):
        await state.set_state(OnboardingStates.entering_display_name)
        await state.update_data(onboard_uid=member.telegram_id)
        await message.answer(
            f"{WELCOME_REGISTERED}\n\n"
            "ملفك غير مكتمل. أرسل الاسم الظاهر الذي تريد أن أخاطبك به:",
        )
        return

    can_roles = False
    with get_db_context() as db:
        from rawafed_bot.services.permission_service import PermissionService
        from rawafed_bot.services.permissions_catalog import MANAGE_ROLES

        m = db.query(Member).filter_by(id=member.id).first()
        can_roles = bool(m and PermissionService.has_permission(db, m, MANAGE_ROLES))

    await message.answer(
        WELCOME_REGISTERED,
        reply_markup=main_menu_keyboard(is_ceo=member.is_ceo, can_roles=can_roles),
    )


async def _start_unregistered(message: Message, state: FSMContext) -> None:
    """No financial menu — begin membership / profile steps."""
    uid = message.from_user.id if message.from_user else 0
    chat = message.chat
    is_group = bool(chat and chat.type in {ChatType.GROUP, ChatType.SUPERGROUP})

    with get_db_context() as db:
        remaining = RegistrationService.remaining_slots(db)
        if uid == settings.CEO_TELEGRAM_ID:
            # CEO missing from DB — unusual; ask to run /setup in group
            await message.answer(
                "حساب الـ CEO غير مهيأ في قاعدة البيانات.\n"
                "نفّذ /setup داخل مجموعة الشركة أولاً.",
            )
            return
        if remaining <= 0:
            await message.answer(
                f"{WELCOME_UNREGISTERED}\n\n"
                f"اكتمل عدد أعضاء الشركة ({settings.MAX_MEMBERS}). "
                "لا يمكن تسجيل عضو إضافي.",
            )
            return
        should, reason = OnboardingService.should_invite(db, uid)
        # already invited / responded still allow restarting title choice from /start
        if reason == "full":
            await message.answer(
                f"{WELCOME_UNREGISTERED}\n\nاكتمل عدد الأعضاء.",
            )
            return
        if is_group:
            OnboardingService.mark_invited(db, uid, chat.id)

    await state.set_state(OnboardingStates.choosing_job_title)
    await state.update_data(onboard_uid=uid)
    await message.answer(
        f"{WELCOME_UNREGISTERED}\n\n"
        "الخطوة 1/3 — اختر المسمى التعريفي (لا يمنح صلاحيات):\n"
        "المناصب الرسمية يعيّنها الـ CEO لاحقاً.",
        reply_markup=_job_keyboard(),
    )
    if not is_group:
        await message.answer(
            "يمكنك إكمال التسجيل هنا اختيارياً، أو من داخل مجموعة الشركة.",
        )
