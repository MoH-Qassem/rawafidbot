"""Expense registration flows."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from rawafed_bot.bot.helpers import handle_cancel, money_line, new_idem_key
from rawafed_bot.bot.keyboards.common import (
    cancel_back_keyboard,
    categories_inline,
    confirm_inline,
    currencies_inline,
    expense_mode_inline,
)
from rawafed_bot.bot.keyboards.main_menu import BTN_EXPENSE, main_menu_keyboard, texts_for
from rawafed_bot.bot.states import ExpenseStates
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.expense_category import ExpenseCategory
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.operation_service import OperationError, OperationService
from rawafed_bot.services.query_service import QueryService
from rawafed_bot.utils.callbacks import CAT, CONFIRM, CUR, EXP_MODE, unpack
from rawafed_bot.utils.money import MoneyError, parse_user_amount

router = Router(name="expense")


@router.message(F.text.in_(texts_for(BTN_EXPENSE)))
async def start_expense(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.services.permissions_catalog import RECORD_EXPENSE
    if not await ensure_perm(message, member, RECORD_EXPENSE):
        return
    await state.clear()
    await state.set_state(ExpenseStates.choosing_mode)
    await message.answer("اختر نوع المصروف:", reply_markup=expense_mode_inline())


@router.callback_query(ExpenseStates.choosing_mode, F.data.startswith(f"{EXP_MODE}:"))
async def choose_mode(callback: CallbackQuery, state: FSMContext):
    mode = unpack(callback.data)[1]
    await state.update_data(mode=mode)
    with get_db_context() as db:
        currencies = QueryService.get_currencies(db)
    await state.set_state(ExpenseStates.choosing_currency)
    await callback.message.edit_text("اختر العملة:", reply_markup=currencies_inline(currencies))
    await callback.answer()


@router.callback_query(ExpenseStates.choosing_currency, F.data.startswith(f"{CUR}:"))
async def choose_currency(callback: CallbackQuery, state: FSMContext):
    currency_id = int(unpack(callback.data)[1])
    await state.update_data(currency_id=currency_id)
    await state.set_state(ExpenseStates.entering_amount)
    await callback.message.edit_text("أدخل المبلغ:")
    await callback.message.answer("المبلغ:", reply_markup=cancel_back_keyboard(include_back=False))
    await callback.answer()


@router.message(ExpenseStates.entering_amount)
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
    with get_db_context() as db:
        cats = QueryService.get_categories(db)
    await state.set_state(ExpenseStates.choosing_category)
    await message.answer("اختر التصنيف:", reply_markup=categories_inline(cats))


@router.callback_query(ExpenseStates.choosing_category, F.data.startswith(f"{CAT}:"))
async def choose_category(callback: CallbackQuery, state: FSMContext):
    category_id = int(unpack(callback.data)[1])
    await state.update_data(category_id=category_id)
    await state.set_state(ExpenseStates.entering_description)
    await callback.message.edit_text("أدخل وصف المصروف:")
    await callback.message.answer("الوصف:", reply_markup=cancel_back_keyboard(include_back=False))
    await callback.answer()


@router.message(ExpenseStates.entering_description)
async def enter_description(message: Message, state: FSMContext):
    from rawafed_bot.bot.helpers import release_if_menu_button
    released = await release_if_menu_button(message, state)
    if released is not None:
        return released
    if await handle_cancel(message, state):
        return
    desc = (message.text or "").strip()
    if not desc:
        await message.answer("الوصف مطلوب.")
        return
    data = await state.get_data()
    key = new_idem_key("expense", data.get("mode"), data["amount"], desc)
    await state.update_data(description=desc, idempotency_key=key)
    with get_db_context() as db:
        currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
        cat = db.query(ExpenseCategory).filter_by(id=data["category_id"]).first()
    if data["mode"] == "box":
        mode_ar = "من الصندوق"
    else:
        mode_ar = "من جيب العضو — الشركة مدينة للعضو بهذا المبلغ"
    summary = (
        "✅ تأكيد تسجيل المصروف\n"
        "━━━━━━━━━━━━\n"
        f"النوع: {mode_ar}\n"
        f"المبلغ: {money_line(data['amount'], currency)}\n"
        f"التصنيف: {cat.name if cat else data['category_id']}\n"
        f"الوصف: {desc}"
    )
    await state.set_state(ExpenseStates.confirming)
    await message.answer(summary, reply_markup=confirm_inline("expense"))


@router.callback_query(ExpenseStates.confirming, F.data == f"{CONFIRM}:expense:yes")
async def confirm_expense(callback: CallbackQuery, state: FSMContext, member: Member):
    data = await state.get_data()
    key = data.get("idempotency_key") or new_idem_key(
        "expense", member.id, data["amount"], data.get("description")
    )
    try:
        with get_db_context() as db:
            if data["mode"] == "box":
                tx = OperationService.record_expense_from_box(
                    db=db, amount=data["amount"], currency_id=data["currency_id"],
                    category_id=data["category_id"], member_id=member.id,
                    description=data["description"], created_by=member.id,
                    idempotency_key=key,
                )
            else:
                tx = OperationService.record_personal_expense(
                    db=db, amount=data["amount"], currency_id=data["currency_id"],
                    category_id=data["category_id"], member_id=member.id,
                    description=data["description"], created_by=member.id,
                    idempotency_key=key,
                )
            currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
            amount_txt = money_line(tx.amount, currency)
            tx_id = tx.id
            from rawafed_bot.bot.notify import notify_group_operation
            await notify_group_operation(callback.bot, db, tx)
        await state.clear()
        await callback.message.edit_text(
            f"✅ تم تسجيل المصروف #{tx_id}\nالمبلغ: {amount_txt}"
        )
        await callback.message.answer(
            "القائمة الرئيسية:",
            reply_markup=main_menu_keyboard(is_ceo=member.is_ceo),
        )
    except OperationError as exc:
        await state.clear()
        await callback.message.answer(
            str(exc), reply_markup=main_menu_keyboard(is_ceo=member.is_ceo)
        )
    except Exception:
        await state.clear()
        await callback.message.answer(
            "تعذر حفظ العملية.",
            reply_markup=main_menu_keyboard(is_ceo=member.is_ceo),
        )
    await callback.answer()
