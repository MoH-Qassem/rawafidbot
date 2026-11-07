"""Member accounts overview."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from rawafed_bot.bot.keyboards.main_menu import BTN_MEMBERS, main_menu_keyboard, texts_for
from rawafed_bot.bot.member_ref import member_is_ceo
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.report_service import ReportService

router = Router(name="members")


@router.message(F.text.in_(texts_for(BTN_MEMBERS)))
async def show_members(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.services.permissions_catalog import VIEW_MEMBERS

    await state.clear()
    if not await ensure_perm(message, member, VIEW_MEMBERS):
        return
    try:
        with get_db_context() as db:
            text = ReportService.member_accounts(db)
        kb = main_menu_keyboard(is_ceo=member_is_ceo(member))
        if len(text) > 4000:
            chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)]
            for chunk in chunks:
                await message.answer(chunk, parse_mode=None)
            await message.answer("—", reply_markup=kb, parse_mode=None)
        else:
            await message.answer(text or "لا يوجد أعضاء.", reply_markup=kb, parse_mode=None)
    except Exception:
        await message.answer(
            "تعذر عرض حسابات الأعضاء. حاول مرة أخرى.",
            reply_markup=main_menu_keyboard(is_ceo=member_is_ceo(member)),
        )
