"""Settings + profile (separate main-menu buttons)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from rawafed_bot.bot.helpers import handle_cancel
from rawafed_bot.bot.keyboards.common import cancel_back_keyboard, settings_menu_inline
from rawafed_bot.bot.keyboards.main_menu import BTN_MY_PROFILE, BTN_SETTINGS, main_menu_keyboard, texts_for
from rawafed_bot.bot.states import SettingsStates
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.backup_service import BackupError, BackupService
from rawafed_bot.services.member_service import MemberService
from rawafed_bot.services.operation_service import OperationError
from rawafed_bot.utils.callbacks import SETTINGS, unpack

router = Router(name="settings")


@router.message(F.text.in_(texts_for(BTN_MY_PROFILE)))
async def profile_entry(message: Message, state: FSMContext, member: Member):
    await state.clear()
    await state.set_state(SettingsStates.menu)
    with get_db_context() as db:
        m = db.query(Member).filter_by(id=member.id).first()
        card = MemberService.profile_card(db, m)
    await message.answer(card[:4000], reply_markup=main_menu_keyboard(is_ceo=member.is_ceo))
    await message.answer(
        "تعديل البيانات الشخصية فقط (الاسم / المسمى التعريفي):",
        reply_markup=settings_menu_inline(show_backup=False),
    )


@router.message(F.text.in_(texts_for(BTN_SETTINGS)))
async def settings_entry(message: Message, state: FSMContext, member: Member):
    await state.clear()
    await state.set_state(SettingsStates.menu)
    can_backup = False
    with get_db_context() as db:
        from rawafed_bot.services.permission_service import PermissionService
        from rawafed_bot.services.permissions_catalog import BACKUP

        m = db.query(Member).filter_by(id=member.id).first()
        can_backup = bool(m and PermissionService.has_permission(db, m, BACKUP))
    await message.answer(
        "⚙️ الإعدادات\n\n"
        "من هنا: تعديل بياناتك الشخصية"
        + ("، والنسخ الاحتياطي." if can_backup else "."),
        reply_markup=settings_menu_inline(show_backup=can_backup),
    )


@router.callback_query(F.data.startswith(f"{SETTINGS}:"))
async def settings_action(callback: CallbackQuery, state: FSMContext, member: Member):
    # Not state-gated: stale inline buttons after /start must still work
    await state.set_state(SettingsStates.menu)
    action = unpack(callback.data)[1]

    if action == "profile":
        with get_db_context() as db:
            m = db.query(Member).filter_by(id=member.id).first()
            text = MemberService.profile_card(db, m)
        try:
            await callback.message.edit_text(text[:4000])
        except Exception:
            await callback.message.answer(text[:4000])
        await callback.answer()
        return

    if action == "edit":
        try:
            await callback.message.edit_text(
                "يمكنك تعديل الاسم الظاهر أو المسمى التعريفي فقط.\n"
                "لا يمكن تغيير المنصب الرسمي أو الصلاحيات من هنا."
            )
        except Exception:
            pass
        await callback.message.answer(
            "اختر:",
            reply_markup=settings_menu_inline(show_backup=False),
        )
        await callback.answer()
        return

    if action == "name":
        await state.set_state(SettingsStates.editing_name)
        try:
            await callback.message.edit_text("أرسل الاسم الظاهر الجديد:")
        except Exception:
            await callback.message.answer("أرسل الاسم الظاهر الجديد:")
        await callback.message.answer("الاسم:", reply_markup=cancel_back_keyboard(include_back=False))
        await callback.answer()
        return

    if action == "title":
        await state.set_state(SettingsStates.editing_title)
        try:
            await callback.message.edit_text("أرسل المسمى الوظيفي الجديد (أو - للمسح):")
        except Exception:
            await callback.message.answer("أرسل المسمى الوظيفي الجديد (أو - للمسح):")
        await callback.message.answer("المسمى:", reply_markup=cancel_back_keyboard(include_back=False))
        await callback.answer()
        return

    if action == "backup":
        with get_db_context() as db:
            from rawafed_bot.services.permission_service import PermissionErrorDenied, PermissionService
            from rawafed_bot.services.permissions_catalog import BACKUP

            m = db.query(Member).filter_by(id=member.id).first()
            try:
                PermissionService.require(db, m, BACKUP)
            except PermissionErrorDenied as exc:
                await callback.answer(str(exc), show_alert=True)
                return
        try:
            from aiogram.types import FSInputFile

            path = BackupService.create_backup(note=f"m{member.id}")
            try:
                await callback.message.edit_text(f"✅ تم إنشاء نسخة احتياطية:\n{path.name}")
            except Exception:
                await callback.message.answer(f"✅ تم إنشاء نسخة احتياطية:\n{path.name}")
            await callback.message.answer_document(
                FSInputFile(path),
                caption="نسخة احتياطية من قاعدة البيانات",
            )
        except BackupError as exc:
            await callback.message.answer(f"فشل النسخ الاحتياطي: {exc}")
        except Exception:
            await callback.message.answer("حدث خطأ أثناء النسخ الاحتياطي.")
        await state.clear()
        await callback.message.answer(
            "القائمة الرئيسية:", reply_markup=main_menu_keyboard(is_ceo=member.is_ceo)
        )
        await callback.answer()
        return

    await callback.answer()


@router.message(SettingsStates.editing_name)
async def edit_name(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers import release_if_menu_button
    from rawafed_bot.bot.member_ref import member_is_ceo

    released = await release_if_menu_button(message, state)
    if released is not None:
        return released
    if await handle_cancel(message, state, member):
        return
    name = (message.text or "").strip()
    try:
        with get_db_context() as db:
            updated = MemberService.update_profile(db, member.id, display_name=name)
            display = updated.get_display_name()
    except OperationError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(
        f"✅ تم تحديث الاسم إلى: {display}",
        reply_markup=main_menu_keyboard(is_ceo=member_is_ceo(member)),
    )


@router.message(SettingsStates.editing_title)
async def edit_title(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers import release_if_menu_button
    from rawafed_bot.bot.member_ref import member_is_ceo

    released = await release_if_menu_button(message, state)
    if released is not None:
        return released
    if await handle_cancel(message, state, member):
        return
    title = (message.text or "").strip()
    if title in {"-", "مسح"}:
        title = ""
    try:
        with get_db_context() as db:
            updated = MemberService.update_profile(db, member.id, job_title=title)
            display = updated.job_title or "—"
    except OperationError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(
        f"✅ تم تحديث المسمى إلى: {display}",
        reply_markup=main_menu_keyboard(is_ceo=member_is_ceo(member)),
    )
