"""Withdrawal flow (final equity withdrawal only — advances removed)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from rawafed_bot.bot.helpers import handle_cancel, money_line, new_idem_key
from rawafed_bot.bot.keyboards.common import (
    cancel_back_keyboard,
    confirm_inline,
    currencies_inline,
)
from rawafed_bot.bot.keyboards.main_menu import (
    BTN_WITHDRAW,
    main_menu_keyboard,
    texts_for,
)
from rawafed_bot.bot.states import WithdrawalStates
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.operation_service import OperationError, OperationService
from rawafed_bot.services.query_service import QueryService
from rawafed_bot.utils.callbacks import CONFIRM, CUR, unpack
from rawafed_bot.utils.money import MoneyError, parse_user_amount

router = Router(name="withdrawal")

# Legacy button label — feature removed
_LEGACY_ADVANCES = {"📦 العهد المالية", "العهد المالية"}


@router.message(F.text.in_(texts_for(BTN_WITHDRAW)))
async def start_withdrawal(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.services.permissions_catalog import RECORD_WITHDRAWAL
    if not await ensure_perm(message, member, RECORD_WITHDRAWAL):
        return
    await state.clear()
    await state.update_data(mode="final")
    with get_db_context() as db:
        currencies = QueryService.get_currencies(db)
    await state.set_state(WithdrawalStates.choosing_currency)
    await message.answer("اختر العملة:", reply_markup=currencies_inline(currencies))


@router.message(F.text.in_(_LEGACY_ADVANCES))
async def advances_removed(message: Message, state: FSMContext, member: Member = None):
    await state.clear()
    is_ceo = bool(member and member.is_ceo)
    await message.answer(
        "تم إلغاء ميزة العهد المالية.\nاستخدم «💳 تسجيل سحب» للسحب النهائي.",
        reply_markup=main_menu_keyboard(is_ceo=is_ceo),
    )


@router.callback_query(WithdrawalStates.choosing_currency, F.data.startswith(f"{CUR}:"))
async def choose_currency(callback: CallbackQuery, state: FSMContext):
    await state.update_data(currency_id=int(unpack(callback.data)[1]), mode="final")
    await state.set_state(WithdrawalStates.entering_amount)
    await callback.message.edit_text("أدخل المبلغ:")
    await callback.message.answer("المبلغ:", reply_markup=cancel_back_keyboard(include_back=False))
    await callback.answer()


@router.message(WithdrawalStates.entering_amount)
async def enter_amount(message: Message, state: FSMContext):
    from rawafed_bot.bot.helpers import release_if_menu_button
    released = await release_if_menu_button(message, state)
    if released is not None:
        return released
    if await handle_cancel(message, state):
        return
    data = await state.get_data()
    with get_db_context() as db:
        currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
        try:
            amount = parse_user_amount(message.text, currency)
        except MoneyError as exc:
            await message.answer(str(exc))
            return
    await state.update_data(amount=amount)
    await state.set_state(WithdrawalStates.entering_description)
    await message.answer("أدخل وصف السحب:", reply_markup=cancel_back_keyboard(include_back=False))


@router.message(WithdrawalStates.entering_description)
async def enter_description(message: Message, state: FSMContext):
    if await handle_cancel(message, state):
        return
    desc = (message.text or "").strip()
    if not desc:
        await message.answer("الوصف مطلوب.")
        return
    data = await state.get_data()
    key = new_idem_key("withdraw", "final", data["amount"], desc)
    await state.update_data(description=desc, idempotency_key=key)
    with get_db_context() as db:
        currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
    summary = (
        f"تأكيد سحب نهائي:\n"
        f"المبلغ: {money_line(data['amount'], currency)}\n"
        f"الوصف: {desc}"
    )
    await state.set_state(WithdrawalStates.confirming)
    await message.answer(summary, reply_markup=confirm_inline("withdraw"))


@router.callback_query(WithdrawalStates.confirming, F.data == f"{CONFIRM}:withdraw:yes")
async def confirm_withdraw(callback: CallbackQuery, state: FSMContext, member: Member):
    data = await state.get_data()
    key = data.get("idempotency_key") or new_idem_key(
        "withdraw", member.id, data["amount"], "final", data.get("description")
    )
    try:
        with get_db_context() as db:
            tx = OperationService.record_withdrawal(
                db=db, amount=data["amount"], currency_id=data["currency_id"],
                member_id=member.id, description=data["description"],
                created_by=member.id, idempotency_key=key,
            )
            currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
            txt = money_line(tx.amount, currency)
            tx_id = tx.id
            from rawafed_bot.bot.notify import notify_group_operation
            await notify_group_operation(callback.bot, db, tx)
        await state.clear()
        await callback.message.edit_text(f"✅ تم التسجيل #{tx_id}\nالمبلغ: {txt}")
        await callback.message.answer(
            "القائمة الرئيسية:",
            reply_markup=main_menu_keyboard(is_ceo=member.is_ceo),
        )
    except OperationError as exc:
        await state.clear()
        await callback.message.answer(
            str(exc), reply_markup=main_menu_keyboard(is_ceo=member.is_ceo)
        )
    await callback.answer()
