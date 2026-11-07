"""Group /setup, welcome message, and member self-registration entry."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from rawafed_bot.bot.keyboards.main_menu import main_menu_keyboard
from rawafed_bot.bot.states import RegistrationStates
from rawafed_bot.core.config import settings
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.group_service import USAGE_HINT, WELCOME_TEXT, GroupError, GroupService
from rawafed_bot.services.registration_service import RegistrationError, RegistrationService
from rawafed_bot.utils.callbacks import REG, SETUP, pack, unpack

router = Router(name="group_setup")


def _register_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="تسجيل عضويتي", callback_data=pack(REG, "me"))],
            [InlineKeyboardButton(text="حالة التسجيل", callback_data=pack(SETUP, "status"))],
        ]
    )


@router.message(Command("setup"))
async def cmd_setup(message: Message, state: FSMContext):
    await state.clear()
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("⚠️ نفّذ /setup داخل مجموعة الشركة.")
        return
    user = message.from_user
    if not user or user.id != settings.CEO_TELEGRAM_ID:
        await message.answer("⛔ تهيئة المجموعة متاحة للـ CEO فقط.")
        return

    full_name = " ".join(x for x in [user.first_name, user.last_name] if x)
    try:
        with get_db_context() as db:
            group, send_welcome = GroupService.setup_group(
                db,
                chat_id=message.chat.id,
                title=message.chat.title or "",
                ceo_telegram_id=user.id,
                telegram_username=user.username,
                telegram_full_name=full_name,
            )
            status = RegistrationService.registration_status(db)
            remaining = status["remaining"]
            count = status["count"]
            max_m = status["max"]
    except GroupError as exc:
        await message.answer(str(exc))
        return

    if send_welcome:
        await message.answer(WELCOME_TEXT, reply_markup=_register_keyboard())
        await message.answer(USAGE_HINT, reply_markup=_register_keyboard())
    else:
        await message.answer(
            "✅ المجموعة مهيأة مسبقاً.\n"
            f"الأعضاء المسجّلون: {count}/{max_m} — المتبقي: {remaining}",
            reply_markup=_register_keyboard(),
        )


@router.message(Command("status"))
async def cmd_status(message: Message):
    with get_db_context() as db:
        status = RegistrationService.registration_status(db)
        lines = [f"👥 الأعضاء: {status['count']}/{status['max']}", "────────────"]
        for m in status["active"]:
            role = "CEO" if m.is_ceo else "عضو"
            lines.append(f"• {m.get_display_name()} — {role}")
        if status["remaining"]:
            lines.append(f"\nالمتبقي للتسجيل: {status['remaining']}")
        else:
            lines.append("\n✅ اكتمل تسجيل الأعضاء.")
    await message.answer("\n".join(lines))


@router.callback_query(F.data == pack(SETUP, "status"))
async def cb_status(callback: CallbackQuery):
    with get_db_context() as db:
        status = RegistrationService.registration_status(db)
        text = f"الأعضاء: {status['count']}/{status['max']} — متبقي {status['remaining']}"
    await callback.answer(text, show_alert=True)


@router.callback_query(F.data.startswith(f"{REG}:"))
async def cb_register(callback: CallbackQuery, state: FSMContext):
    action = unpack(callback.data)[1]
    if action != "me":
        await callback.answer("خيار غير معروف", show_alert=True)
        return

    user = callback.from_user
    if user is None:
        await callback.answer("تعذر التعرف على المستخدم", show_alert=True)
        return

    # Only the clicking user can register themselves
    full_name = " ".join(x for x in [user.first_name, user.last_name] if x)
    group_db_id = None
    try:
        with get_db_context() as db:
            chat = callback.message.chat if callback.message else None
            if chat and chat.type in {"group", "supergroup"}:
                group = GroupService.get_by_chat_id(db, chat.id)
                if not group or not group.is_setup_complete:
                    await callback.answer("يجب على الـ CEO تنفيذ /setup أولاً", show_alert=True)
                    return
                group_db_id = group.id
            member = RegistrationService.register_self(
                db,
                telegram_id=user.id,
                telegram_username=user.username,
                telegram_full_name=full_name,
                group_id=group_db_id,
            )
            status = RegistrationService.registration_status(db)
            need_profile = not member.profile_completed
            member_id = member.id
    except RegistrationError as exc:
        await callback.answer(str(exc)[:180], show_alert=True)
        return

    await callback.answer("✅ تم تسجيلك", show_alert=True)
    await callback.message.answer(
        f"مرحباً! تم تسجيلك بنجاح.\n"
        f"الأعضاء الآن: {status['count']}/{status['max']}"
    )
    if need_profile:
        profile_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="✏️ إكمال الملف الشخصي",
                    callback_data=pack(REG, "profile"),
                )]
            ]
        )
        await callback.message.answer(
            "أكمل ملفك الشخصي هنا داخل المجموعة:",
            reply_markup=profile_kb,
        )


@router.callback_query(F.data == pack(REG, "profile"))
async def cb_complete_profile(callback: CallbackQuery, state: FSMContext, member: Member = None):
    user = callback.from_user
    if not user:
        await callback.answer("خطأ", show_alert=True)
        return
    with get_db_context() as db:
        m = db.query(Member).filter_by(telegram_id=user.id, is_active=True).first()
        if not m:
            await callback.answer("سجّل عضويتك أولاً", show_alert=True)
            return
        mid = m.id
    await state.set_state(RegistrationStates.entering_display_name)
    await state.update_data(reg_member_id=mid)
    await callback.message.answer("✏️ أرسل اسمك الظاهر الذي سيظهر في السجلات:")
    await callback.answer()


@router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    user = message.from_user
    if not user:
        return
    with get_db_context() as db:
        m = db.query(Member).filter_by(telegram_id=user.id, is_active=True).first()
        if not m:
            await message.answer("سجّل عضويتك من المجموعة أولاً عبر «تسجيل عضويتي».")
            return
        mid = m.id
    await state.set_state(RegistrationStates.entering_display_name)
    await state.update_data(reg_member_id=mid)
    await message.answer("✏️ أرسل اسمك الظاهر:")


@router.message(RegistrationStates.entering_display_name)
async def reg_display_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name or len(name) > 100:
        await message.answer("الاسم غير صالح. أعد المحاولة.")
        return
    await state.update_data(display_name=name)
    await state.set_state(RegistrationStates.entering_job_title)
    await message.answer("أرسل مسمّاك الوظيفي (أو أرسل - للتخطي):")


@router.message(RegistrationStates.entering_job_title)
async def reg_job_title(message: Message, state: FSMContext):
    data = await state.get_data()
    title = (message.text or "").strip()
    if title == "-":
        title = None
    try:
        with get_db_context() as db:
            member = RegistrationService.complete_profile(
                db,
                member_id=data["reg_member_id"],
                display_name=data["display_name"],
                job_title=title,
            )
            display = member.get_display_name()
    except RegistrationError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(
        f"✅ اكتمل ملفك: {display}\nيمكنك الآن استخدام القائمة المالية.",
        reply_markup=main_menu_keyboard(),
    )


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated):
    """Track bot removal from group — no financial impact."""
    new = event.new_chat_member
    if new.status in {"left", "kicked"} and event.chat.type in {"group", "supergroup"}:
        with get_db_context() as db:
            GroupService.mark_bot_removed(db, event.chat.id)
