"""Group intelligence: accountant addressing, onboarding, member events — group-first."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from rawafed_bot.bot.filters_group import GroupIntelligenceFilter
from rawafed_bot.bot.handlers.group_ops import start_group_operation
from rawafed_bot.bot.keyboards.main_menu import main_menu_keyboard
from rawafed_bot.bot.states import OnboardingStates
from rawafed_bot.core.config import settings
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.addressing import is_addressed_to_accountant, is_bot_message
from rawafed_bot.services.auth_service import AuthService
from rawafed_bot.services.group_service import GroupService
from rawafed_bot.services.intent_router import IntentRouter
from rawafed_bot.services.onboarding_service import JOB_TITLE_PRESETS, OnboardingService
from rawafed_bot.services.permission_service import PermissionService
from rawafed_bot.services.registration_service import RegistrationError, RegistrationService
from rawafed_bot.services.role_transfer_service import RoleTransferService
from rawafed_bot.utils.callbacks import JOB, pack, unpack

logger = logging.getLogger(__name__)
router = Router(name="group_chat")

WELCOME_ASK = (
    "مرحباً بك في مجموعة شركة روافد.\n"
    "سنكمل ملفك هنا داخل المجموعة.\n\n"
    "<i>المسمى الذي تختاره تعريفي؛ المنصب الرسمي والصلاحيات يحددها الـ CEO.</i>"
)


def _job_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=pack(JOB, code))]
        for code, label in JOB_TITLE_PRESETS
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _mention(user) -> str:
    name = user.full_name if user else "عضو"
    uid = user.id if user else 0
    return f'<a href="tg://user?id={uid}">{name}</a>'


@router.message(OnboardingStates.waiting_custom_title, F.text)
@router.message(OnboardingStates.entering_display_name, F.text)
@router.message(OnboardingStates.entering_nickname, F.text)
async def onboarding_text_steps(message: Message, state: FSMContext, bot: Bot):
    if not message.from_user:
        return
    data = await state.get_data()
    if data.get("onboard_uid") and data["onboard_uid"] != message.from_user.id:
        return
    current = await state.get_state()
    mention = _mention(message.from_user)

    if current == OnboardingStates.waiting_custom_title.state:
        await _finish_job_and_ask_name(message, state, bot, "other", message.text.strip())
        return

    if current == OnboardingStates.entering_display_name.state:
        name = (message.text or "").strip()
        if not name or len(name) > 100:
            await message.reply(f"{mention}\nالاسم غير صالح. أعد الإرسال.")
            return
        await state.update_data(display_name=name)
        await state.set_state(OnboardingStates.entering_nickname)
        await message.reply(
            f"{mention}\nهل تريد لقباً أو طريقة مخاطبة خاصة؟\n"
            "أرسل اللقب أو اكتب <b>تخطي</b>."
        )
        return

    if current == OnboardingStates.entering_nickname.state:
        nick = (message.text or "").strip()
        if nick in {"تخطي", "-", "لا"}:
            nick = None
        await state.update_data(nickname=nick)
        await _review_and_save_profile(message, state, bot)
        return


@router.message(GroupIntelligenceFilter())
async def group_text_message(message: Message, state: FSMContext, bot: Bot, member: Member = None):
    if not message.from_user or is_bot_message(message, bot.id):
        return

    # Don't steal replies while collecting financial fields
    cur_state = await state.get_state()
    if cur_state and str(cur_state).startswith("GroupOpStates"):
        return UNHANDLED

    me = await bot.me()
    user = message.from_user
    text = message.text or ""

    with get_db_context() as db:
        registered = OnboardingService.is_registered(db, user.id)
        active_member = AuthService.get_member_by_telegram_id(db, user.id)
        if active_member and not active_member.is_active:
            active_member = None

        if not registered:
            should, reason = OnboardingService.should_invite(db, user.id)
            if reason == "full":
                if is_addressed_to_accountant(message, me):
                    await message.reply("التسجيل مغلق حالياً — اكتمل عدد أعضاء الشركة (5).")
                return
            if should:
                OnboardingService.mark_invited(db, user.id, message.chat.id)
                await state.set_state(OnboardingStates.choosing_job_title)
                await state.update_data(onboard_uid=user.id)
                await message.reply(
                    f"{_mention(user)}\n{WELCOME_ASK}\n\nما منصبك في الشركة؟",
                    reply_markup=_job_keyboard(),
                )
                try:
                    await bot.send_message(
                        settings.CEO_TELEGRAM_ID,
                        f"👋 عضو جديد بدأ التسجيل في المجموعة: {user.full_name}",
                    )
                except Exception:
                    pass
                return
            if is_addressed_to_accountant(message, me):
                await message.reply(
                    f"{_mention(user)}\nأكمل اختيار المسمى من الأزرار أولاً."
                )
            return

        if not is_addressed_to_accountant(message, me):
            return

        mem = active_member or member
        if not mem:
            await message.reply("حسابك غير نشط. تواصل مع الـ CEO.")
            return

        mem = db.query(Member).filter_by(id=mem.id).first()
        caller = mem.get_display_name() if mem else user.full_name
        result = IntentRouter.route(db, mem, text, caller)

        if result.intent == "write_op" and result.parsed_op:
            # Detach member for use outside session
            mid = mem.id
            db.expunge(mem)
            await start_group_operation(message, state, mem, result.parsed_op)
            return

        await message.reply(result.reply)


@router.callback_query(F.data.startswith(f"{JOB}:"))
async def job_title_chosen(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user = callback.from_user
    if not user:
        await callback.answer("خطأ", show_alert=True)
        return
    data = await state.get_data()
    if data.get("onboard_uid") and data["onboard_uid"] != user.id:
        await callback.answer("هذا السؤال موجّه لعضو آخر", show_alert=True)
        return

    code = unpack(callback.data)[1]
    if code == "other":
        await state.set_state(OnboardingStates.waiting_custom_title)
        await state.update_data(onboard_uid=user.id)
        await callback.message.answer(f"{_mention(user)}\n✍️ اكتب مسمّاك الوظيفي:")
        await callback.answer()
        return

    await callback.answer()
    await _finish_job_and_ask_name(callback.message, state, bot, code, None, user=user)


async def _finish_job_and_ask_name(
    message: Message,
    state: FSMContext,
    bot: Bot,
    code: str,
    custom_title: str = None,
    user=None,
):
    user = user or message.from_user
    full_name = " ".join(x for x in [user.first_name, user.last_name] if x)
    transfer_note = ""
    try:
        with get_db_context() as db:
            if OnboardingService.is_registered(db, user.id):
                # Already registered — just update title display
                mem = db.query(Member).filter_by(telegram_id=user.id).first()
                from rawafed_bot.services.member_service import MemberService
                from rawafed_bot.services.onboarding_service import JOB_TITLE_BY_CODE
                title = custom_title if code == "other" else JOB_TITLE_BY_CODE.get(code, code)
                MemberService.update_profile(db, mem.id, job_title=title)
            else:
                group_db_id = None
                if message.chat.type in {"group", "supergroup"}:
                    g = GroupService.get_by_chat_id(db, message.chat.id)
                    group_db_id = g.id if g else None
                member = OnboardingService.apply_job_title_choice(
                    db,
                    telegram_id=user.id,
                    title_code=code,
                    custom_title=custom_title,
                    telegram_username=user.username,
                    telegram_full_name=full_name,
                    group_id=group_db_id,
                )
                # Unique official role request if mapped and occupied
                note = RoleTransferService.maybe_request_on_title(
                    db, member, code, bot_notify=False
                )
                if note:
                    transfer_note = "\n\n" + note
                try:
                    await bot.send_message(
                        settings.CEO_TELEGRAM_ID,
                        OnboardingService.notify_ceo_text(
                            member.get_display_name(),
                            member.job_title or "",
                            RegistrationService.remaining_slots(db),
                        ),
                    )
                except Exception:
                    pass
    except RegistrationError as exc:
        await message.answer(str(exc))
        return

    await state.set_state(OnboardingStates.entering_display_name)
    await state.update_data(onboard_uid=user.id)
    await message.answer(
        f"{_mention(user)}\nما الاسم الذي تريد أن أخاطبك به؟{transfer_note}"
    )


async def _review_and_save_profile(message: Message, state: FSMContext, bot: Bot):
    user = message.from_user
    data = await state.get_data()
    display = data.get("display_name")
    nick = data.get("nickname")
    if nick:
        display = f"{display} ({nick})"
    try:
        with get_db_context() as db:
            mem = db.query(Member).filter_by(telegram_id=user.id, is_active=True).first()
            if not mem:
                await message.answer("سجّل أولاً عبر اختيار المسمى.")
                return
            from rawafed_bot.services.registration_service import RegistrationService as RS
            RS.complete_profile(db, mem.id, display_name=data.get("display_name"), job_title=mem.job_title)
            if nick:
                from rawafed_bot.services.member_service import MemberService
                # keep job_title; append nick into display already done via complete_profile name
            role = PermissionService.get_member_role(db, mem.id)
            summary = (
                f"✅ تم حفظ ملفك داخل المجموعة.\n\n"
                f"• الاسم: {data.get('display_name')}\n"
                f"• المسمى التعريفي: {mem.job_title or '—'}\n"
                f"• اللقب: {nick or '—'}\n"
                f"• Username: @{user.username or '—'}\n"
                f"• المنصب الرسمي: {role.name_ar if role else '—'}\n\n"
                "يمكنك استخدام القائمة أو كتابة: يا محاسب، …"
            )
            is_ceo = mem.is_ceo
    except Exception as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(summary, reply_markup=main_menu_keyboard(is_ceo=is_ceo))


@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_member_join(event: ChatMemberUpdated, bot: Bot, state: FSMContext = None):
    user = event.new_chat_member.user
    if not user or user.is_bot:
        return
    with get_db_context() as db:
        should, reason = OnboardingService.should_invite(db, user.id)
        if not should:
            return
        OnboardingService.mark_invited(db, user.id, event.chat.id)
    try:
        await bot.send_message(
            event.chat.id,
            f"{_mention(user)}\n{WELCOME_ASK}\n\nما منصبك في الشركة؟",
            reply_markup=_job_keyboard(),
        )
    except Exception:
        logger.exception("join welcome failed")


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_member_leave(event: ChatMemberUpdated):
    user = event.old_chat_member.user if event.old_chat_member else None
    if user and not user.is_bot:
        logger.info("Member left group chat_id=%s user_id=%s", event.chat.id, user.id)
