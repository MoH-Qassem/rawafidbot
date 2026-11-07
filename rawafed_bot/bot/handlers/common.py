"""Cancel and shared confirm helpers ( /start lives in handlers.start )."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from rawafed_bot.bot.helpers import is_cancel
from rawafed_bot.bot.keyboards.main_menu import main_menu_keyboard
from rawafed_bot.database.models.member import Member
from rawafed_bot.utils.callbacks import CONFIRM

router = Router(name="common")


@router.message(Command("cancel"))
@router.message(F.text.func(lambda t: is_cancel(t)))
async def cmd_cancel(message: Message, state: FSMContext, member: Member = None):
    current = await state.get_state()
    await state.clear()
    is_ceo = bool(member and member.is_ceo)
    if current:
        await message.answer("تم إلغاء العملية.", reply_markup=main_menu_keyboard(is_ceo=is_ceo))
    else:
        await message.answer("لا توجد عملية جارية.", reply_markup=main_menu_keyboard(is_ceo=is_ceo))


@router.callback_query(F.data.startswith(f"{CONFIRM}:") & F.data.endswith(":no"))
async def confirm_cancel_generic(callback: CallbackQuery, state: FSMContext, member: Member = None):
    await state.clear()
    is_ceo = bool(member and member.is_ceo)
    try:
        await callback.message.edit_text("تم الإلغاء.")
    except Exception:
        pass
    await callback.message.answer(
        "القائمة الرئيسية:",
        reply_markup=main_menu_keyboard(is_ceo=is_ceo),
    )
    await callback.answer()
