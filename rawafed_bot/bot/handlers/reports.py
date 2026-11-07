"""Financial reports handlers — summary / weekly / monthly / Excel."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from rawafed_bot.bot.keyboards.common import reports_menu_inline
from rawafed_bot.bot.keyboards.main_menu import (
    BTN_EXPORT,
    BTN_MONTHLY,
    BTN_REPORT,
    BTN_WEEKLY,
    main_menu_keyboard,
    texts_for,
)
from rawafed_bot.bot.states import ReportStates
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.report_service import ReportService
from rawafed_bot.utils.callbacks import REPORT, unpack

router = Router(name="reports")


def _menu_kb(member: Member):
    from rawafed_bot.bot.member_ref import member_is_ceo
    return main_menu_keyboard(is_ceo=member_is_ceo(member))


@router.message(F.text.in_(texts_for(BTN_REPORT)))
async def report_financial(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.services.permissions_catalog import VIEW_REPORTS

    if not await ensure_perm(message, member, VIEW_REPORTS):
        return
    await state.clear()
    with get_db_context() as db:
        text = ReportService.full_summary(db)
    await message.answer(text[:4000], reply_markup=_menu_kb(member))
    await message.answer("تقارير إضافية:", reply_markup=reports_menu_inline())
    await state.set_state(ReportStates.menu)


@router.message(F.text.in_(texts_for(BTN_WEEKLY)))
async def report_weekly(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.services.permissions_catalog import EXPORT_EXCEL, VIEW_REPORTS

    if not await ensure_perm(message, member, VIEW_REPORTS):
        return
    if not await ensure_perm(message, member, EXPORT_EXCEL):
        return
    await state.clear()
    with get_db_context() as db:
        text, path = ReportService.weekly_report(db)
    await message.answer(text[:3500], reply_markup=_menu_kb(member))
    await message.answer_document(FSInputFile(str(path)), caption="تقرير أسبوعي Excel")


@router.message(F.text.in_(texts_for(BTN_MONTHLY)))
async def report_monthly(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.services.permissions_catalog import EXPORT_EXCEL, VIEW_REPORTS

    if not await ensure_perm(message, member, VIEW_REPORTS):
        return
    if not await ensure_perm(message, member, EXPORT_EXCEL):
        return
    await state.clear()
    with get_db_context() as db:
        text, path = ReportService.monthly_report(db)
    await message.answer(text[:3500], reply_markup=_menu_kb(member))
    await message.answer_document(FSInputFile(str(path)), caption="تقرير شهري Excel")


@router.message(F.text.in_(texts_for(BTN_EXPORT)))
async def export_excel(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.services.permissions_catalog import EXPORT_EXCEL

    if not await ensure_perm(message, member, EXPORT_EXCEL):
        return
    await state.clear()
    with get_db_context() as db:
        path = ReportService.export_excel(db, title="تقرير_مالي")
    await message.answer_document(
        FSInputFile(str(path)),
        caption="📥 ملف Excel",
        reply_markup=_menu_kb(member),
    )


@router.callback_query(ReportStates.menu, F.data.startswith(f"{REPORT}:"))
async def report_action(callback: CallbackQuery, state: FSMContext, member: Member):
    from rawafed_bot.services.permission_service import PermissionErrorDenied, PermissionService
    from rawafed_bot.services.permissions_catalog import EXPORT_EXCEL, VIEW_REPORTS

    action = unpack(callback.data)[1]
    with get_db_context() as db:
        m = db.query(Member).filter_by(id=member.id).first()
        try:
            PermissionService.require(db, m, VIEW_REPORTS)
            if action in {"week", "month"}:
                PermissionService.require(db, m, EXPORT_EXCEL)
        except PermissionErrorDenied as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        if action == "cash":
            text = ReportService.cash_box_report(db)
            await callback.message.edit_text(text[:4000])
        elif action == "exp":
            text = ReportService.expenses_by_category(db)
            await callback.message.edit_text(text[:4000])
        elif action == "week":
            text, path = ReportService.weekly_report(db)
            await callback.message.edit_text(text[:3500])
            await callback.message.answer_document(
                FSInputFile(str(path)), caption="تقرير أسبوعي Excel"
            )
        elif action == "month":
            text, path = ReportService.monthly_report(db)
            await callback.message.edit_text(text[:3500])
            await callback.message.answer_document(
                FSInputFile(str(path)), caption="تقرير شهري Excel"
            )
        else:
            await callback.answer("خيار غير معروف", show_alert=True)
            return
    await callback.message.answer("القائمة الرئيسية:", reply_markup=_menu_kb(member))
    await state.clear()
    await callback.answer()
