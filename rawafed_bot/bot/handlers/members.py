"""Member accounts overview."""
from aiogram import F, Router
from aiogram.types import Message

from rawafed_bot.bot.keyboards.main_menu import BTN_MEMBERS, main_menu_keyboard, texts_for
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.report_service import ReportService

router = Router(name="members")


@router.message(F.text.in_(texts_for(BTN_MEMBERS)))
async def show_members(message: Message, member: Member):
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.services.permissions_catalog import VIEW_MEMBERS
    if not await ensure_perm(message, member, VIEW_MEMBERS):
        return
    with get_db_context() as db:
        text = ReportService.member_accounts(db)
    kb = main_menu_keyboard(is_ceo=member.is_ceo)
    if len(text) > 4000:
        chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)]
        for chunk in chunks:
            await message.answer(chunk)
        await message.answer("—", reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)
