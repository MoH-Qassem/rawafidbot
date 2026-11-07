"""Shared bot helpers."""
from __future__ import annotations

from typing import Optional

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from rawafed_bot.bot.keyboards.main_menu import all_ceo_buttons, all_member_buttons
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.transaction import TransactionType
from rawafed_bot.utils.idempotency import generate_idempotency_key, generate_uuid
from rawafed_bot.utils.money import format_amount

CANCEL_TEXTS = {"إلغاء", "/cancel", "الغاء", "cancel"}
BACK_TEXTS = {"رجوع", "⬅️ رجوع", "back"}
MAIN_MENU_TEXTS = set(all_member_buttons()) | set(all_ceo_buttons())

TX_TYPE_AR = {
    TransactionType.DEPOSIT.value: "إيداع",
    TransactionType.EXPENSE.value: "مصروف",
    TransactionType.WITHDRAWAL.value: "سحب",
    TransactionType.PERSONAL_EXPENSE.value: "مصروف شخصي",
    TransactionType.DEBT_REPAYMENT.value: "تسديد دين",
    TransactionType.ADVANCE_ISSUED.value: "عهدة",
    TransactionType.ADVANCE_SETTLEMENT.value: "تسوية عهدة",
    TransactionType.REVERSAL.value: "عكس عملية",
}


def is_cancel(text: Optional[str]) -> bool:
    return (text or "").strip() in CANCEL_TEXTS


def is_back(text: Optional[str]) -> bool:
    return (text or "").strip() in BACK_TEXTS


def new_idem_key(*parts) -> str:
    return generate_idempotency_key(*[str(p) for p in parts], generate_uuid())


def money_line(amount: int, currency: Currency) -> str:
    return format_amount(amount, currency)


async def clear_and_reply(message: Message, state: FSMContext, text: str, reply_markup=None):
    await state.clear()
    await message.answer(text, reply_markup=reply_markup)


async def handle_cancel(message: Message, state: FSMContext) -> bool:
    """If message is cancel, clear state and reply. Returns True when handled."""
    from rawafed_bot.bot.keyboards.main_menu import main_menu_keyboard

    if not is_cancel(message.text):
        return False
    await state.clear()
    await message.answer("تم إلغاء العملية.", reply_markup=main_menu_keyboard())
    return True
