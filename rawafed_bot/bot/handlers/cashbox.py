"""Cash box status."""
from aiogram import F, Router
from aiogram.types import Message

from rawafed_bot.bot.keyboards.main_menu import BTN_CASHBOX, main_menu_keyboard, texts_for
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.report_service import ReportService

router = Router(name="cashbox")


@router.message(F.text.in_(texts_for(BTN_CASHBOX)))
async def show_cashbox(message: Message, member: Member):
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.services.permissions_catalog import VIEW_CASHBOX
    if not await ensure_perm(message, member, VIEW_CASHBOX):
        return
    with get_db_context() as db:
        text = ReportService.cash_box_report(db)
    await message.answer(text, reply_markup=main_menu_keyboard(is_ceo=member.is_ceo))
