"""Withdrawal, advance issue, and advance settlement flows."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from rawafed_bot.bot.helpers import handle_cancel, money_line, new_idem_key
from rawafed_bot.bot.keyboards.common import (
    advances_inline,
    cancel_back_keyboard,
    categories_inline,
    confirm_inline,
    currencies_inline,
    withdrawal_mode_inline,
)
from rawafed_bot.bot.keyboards.main_menu import (
    BTN_ADVANCES,
    BTN_WITHDRAW,
    main_menu_keyboard,
    texts_for,
)
from rawafed_bot.bot.states import WithdrawalStates
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.advance import Advance
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.operation_service import OperationError, OperationService
from rawafed_bot.services.query_service import QueryService
from rawafed_bot.utils.callbacks import ADV, CAT, CONFIRM, CUR, WD_MODE, unpack
from rawafed_bot.utils.money import MoneyError, format_amount, parse_user_amount

router = Router(name="withdrawal")


@router.message(F.text.in_(texts_for(BTN_WITHDRAW)))
async def start_withdrawal(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.services.permissions_catalog import RECORD_WITHDRAWAL
    if not await ensure_perm(message, member, RECORD_WITHDRAWAL):
        return
    await state.clear()
    await state.set_state(WithdrawalStates.choosing_mode)
    await message.answer("اختر نوع السحب:", reply_markup=withdrawal_mode_inline())


@router.message(F.text.in_(texts_for(BTN_ADVANCES)))
async def advances_entry(message: Message, state: FSMContext, member: Member):
    """Dedicated advances hub — list open advances + settle / issue."""
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.services.permissions_catalog import RECORD_WITHDRAWAL, VIEW_HISTORY

    # Viewing open advances needs history/cash visibility; issuing needs withdrawal
    if not await ensure_perm(message, member, VIEW_HISTORY):
        return
    await state.clear()
    with get_db_context() as db:
        advances = QueryService.open_advances(db)
        lines = ["📦 العهد المالية المفتوحة", "────────────"]
        items = []
        for a in advances:
            cur = db.query(Currency).filter_by(id=a.currency_id).first()
            m = db.query(Member).filter_by(id=a.member_id).first()
            label = (
                f"#{a.id} {m.get_display_name() if m else a.member_id} — "
                f"{format_amount(a.amount, cur)}"
            )
            lines.append(label)
            items.append((a.id, label))
        if not advances:
            lines.append("لا توجد عهد مفتوحة حالياً.")
        text = "\n".join(lines)
    await message.answer(text[:4000], reply_markup=main_menu_keyboard(is_ceo=member.is_ceo))
    can_wd = False
    with get_db_context() as db:
        from rawafed_bot.services.permission_service import PermissionService
        m = db.query(Member).filter_by(id=member.id).first()
        can_wd = bool(m and PermissionService.has_permission(db, m, RECORD_WITHDRAWAL))
    if can_wd:
        await state.set_state(WithdrawalStates.choosing_mode)
        await message.answer(
            "لإصدار عهدة جديدة أو تسوية عهدة مفتوحة:",
            reply_markup=withdrawal_mode_inline(),
        )
    elif items:
        await message.answer("عرض العهد متاح. إصدار/تسوية العهد يتطلب صلاحية السحب.")


@router.callback_query(WithdrawalStates.choosing_mode, F.data.startswith(f"{WD_MODE}:"))
async def choose_mode(callback: CallbackQuery, state: FSMContext, member: Member):
    mode = unpack(callback.data)[1]
    await state.update_data(mode=mode)
    if mode == "settle":
        with get_db_context() as db:
            advances = QueryService.open_advances(db)
            items = []
            for a in advances:
                cur = db.query(Currency).filter_by(id=a.currency_id).first()
                m = db.query(Member).filter_by(id=a.member_id).first()
                items.append((
                    a.id,
                    f"#{a.id} {m.get_display_name() if m else a.member_id} — {format_amount(a.amount, cur)}",
                ))
        if not items:
            await state.clear()
            await callback.message.edit_text("لا توجد عهد مفتوحة للتسوية.")
            await callback.message.answer("القائمة:", reply_markup=main_menu_keyboard())
            await callback.answer()
            return
        await state.set_state(WithdrawalStates.choosing_advance)
        await callback.message.edit_text("اختر العهدة:", reply_markup=advances_inline(items))
        await callback.answer()
        return

    with get_db_context() as db:
        currencies = QueryService.get_currencies(db)
    await state.set_state(WithdrawalStates.choosing_currency)
    await callback.message.edit_text("اختر العملة:", reply_markup=currencies_inline(currencies))
    await callback.answer()


@router.callback_query(WithdrawalStates.choosing_currency, F.data.startswith(f"{CUR}:"))
async def choose_currency(callback: CallbackQuery, state: FSMContext):
    await state.update_data(currency_id=int(unpack(callback.data)[1]))
    await state.set_state(WithdrawalStates.entering_amount)
    await callback.message.edit_text("أدخل المبلغ:")
    await callback.message.answer("المبلغ:", reply_markup=cancel_back_keyboard(include_back=False))
    await callback.answer()


@router.message(WithdrawalStates.entering_amount)
async def enter_amount(message: Message, state: FSMContext):
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
    if data.get("mode") == "advance":
        await state.set_state(WithdrawalStates.entering_purpose)
        await message.answer("أدخل غرض العهدة:", reply_markup=cancel_back_keyboard(include_back=False))
    else:
        await state.set_state(WithdrawalStates.entering_description)
        await message.answer("أدخل وصف السحب:", reply_markup=cancel_back_keyboard(include_back=False))


@router.message(WithdrawalStates.entering_purpose)
async def enter_purpose(message: Message, state: FSMContext):
    if await handle_cancel(message, state):
        return
    purpose = (message.text or "").strip()
    if not purpose:
        await message.answer("الغرض مطلوب.")
        return
    await state.update_data(purpose=purpose)
    await state.set_state(WithdrawalStates.entering_description)
    await message.answer("أدخل وصف العملية:", reply_markup=cancel_back_keyboard(include_back=False))


@router.message(WithdrawalStates.entering_description)
async def enter_description(message: Message, state: FSMContext):
    if await handle_cancel(message, state):
        return
    desc = (message.text or "").strip()
    if not desc:
        await message.answer("الوصف مطلوب.")
        return
    data = await state.get_data()
    key = new_idem_key("withdraw", data.get("mode"), data["amount"], desc)
    await state.update_data(description=desc, idempotency_key=key)
    with get_db_context() as db:
        currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
    mode = data.get("mode")
    mode_ar = "سحب نهائي" if mode == "final" else "عهدة مؤقتة"
    summary = (
        f"تأكيد {mode_ar}:\n"
        f"المبلغ: {money_line(data['amount'], currency)}\n"
        f"الوصف: {desc}"
    )
    if mode == "advance":
        summary += f"\nالغرض: {data.get('purpose')}"
    await state.set_state(WithdrawalStates.confirming)
    await message.answer(summary, reply_markup=confirm_inline("withdraw"))


@router.callback_query(WithdrawalStates.confirming, F.data == f"{CONFIRM}:withdraw:yes")
async def confirm_withdraw(callback: CallbackQuery, state: FSMContext, member: Member):
    data = await state.get_data()
    key = data.get("idempotency_key") or new_idem_key(
        "withdraw", member.id, data["amount"], data.get("mode"), data.get("description")
    )
    try:
        with get_db_context() as db:
            if data.get("mode") == "advance":
                tx, advance = OperationService.record_withdrawal_as_advance(
                    db=db, amount=data["amount"], currency_id=data["currency_id"],
                    member_id=member.id, description=data["description"],
                    purpose=data.get("purpose") or data["description"],
                    created_by=member.id, idempotency_key=key,
                )
                extra = f"\nرقم العهدة: #{advance.id}"
            else:
                tx = OperationService.record_withdrawal(
                    db=db, amount=data["amount"], currency_id=data["currency_id"],
                    member_id=member.id, description=data["description"],
                    created_by=member.id, idempotency_key=key,
                )
                extra = ""
            currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
            txt = money_line(tx.amount, currency)
            tx_id = tx.id
            from rawafed_bot.bot.notify import notify_group_operation
            await notify_group_operation(callback.bot, db, tx)
        await state.clear()
        await callback.message.edit_text(f"✅ تم التسجيل #{tx_id}\nالمبلغ: {txt}{extra}")
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


# --- settle advance ---

@router.callback_query(WithdrawalStates.choosing_advance, F.data.startswith(f"{ADV}:"))
async def choose_advance(callback: CallbackQuery, state: FSMContext):
    advance_id = int(unpack(callback.data)[1])
    await state.update_data(advance_id=advance_id)
    await state.set_state(WithdrawalStates.entering_expense_amount)
    await callback.message.edit_text("أدخل مبلغ المصروف من العهدة (0 إذا لا يوجد):")
    await callback.message.answer("مبلغ المصروف:", reply_markup=cancel_back_keyboard(include_back=False))
    await callback.answer()


@router.message(WithdrawalStates.entering_expense_amount)
async def enter_expense_amount(message: Message, state: FSMContext):
    if await handle_cancel(message, state):
        return
    data = await state.get_data()
    with get_db_context() as db:
        adv = db.query(Advance).filter_by(id=data["advance_id"]).first()
        currency = db.query(Currency).filter_by(id=adv.currency_id).first()
        try:
            amount = parse_user_amount(message.text or "0", currency)
        except MoneyError as exc:
            await message.answer(str(exc))
            return
        currency_id = currency.id
    await state.update_data(expense_amount=amount, currency_id=currency_id)
    await state.set_state(WithdrawalStates.entering_returned_amount)
    await message.answer("أدخل المبلغ المعاد للصندوق (0 إذا لا يوجد):")


@router.message(WithdrawalStates.entering_returned_amount)
async def enter_returned_amount(message: Message, state: FSMContext):
    if await handle_cancel(message, state):
        return
    data = await state.get_data()
    with get_db_context() as db:
        currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
        try:
            amount = parse_user_amount(message.text or "0", currency)
        except MoneyError as exc:
            await message.answer(str(exc))
            return
        cats = QueryService.get_categories(db)
    await state.update_data(returned_amount=amount)
    if data.get("expense_amount", 0) > 0:
        await state.set_state(WithdrawalStates.choosing_settle_category)
        await message.answer("اختر تصنيف المصروف:", reply_markup=categories_inline(cats))
    else:
        await state.update_data(category_id=None)
        await state.set_state(WithdrawalStates.entering_settle_description)
        await message.answer("أدخل وصف التسوية:", reply_markup=cancel_back_keyboard(include_back=False))


@router.callback_query(WithdrawalStates.choosing_settle_category, F.data.startswith(f"{CAT}:"))
async def choose_settle_category(callback: CallbackQuery, state: FSMContext):
    await state.update_data(category_id=int(unpack(callback.data)[1]))
    await state.set_state(WithdrawalStates.entering_settle_description)
    await callback.message.edit_text("أدخل وصف التسوية:")
    await callback.message.answer("الوصف:", reply_markup=cancel_back_keyboard(include_back=False))
    await callback.answer()


@router.message(WithdrawalStates.entering_settle_description)
async def enter_settle_description(message: Message, state: FSMContext):
    if await handle_cancel(message, state):
        return
    desc = (message.text or "").strip()
    if not desc:
        await message.answer("الوصف مطلوب.")
        return
    data = await state.get_data()
    key = new_idem_key(
        "settle", data["advance_id"], data["expense_amount"], data["returned_amount"]
    )
    await state.update_data(description=desc, idempotency_key=key)
    with get_db_context() as db:
        currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
        adv = db.query(Advance).filter_by(id=data["advance_id"]).first()
        adv_amount = adv.amount
    summary = (
        f"تأكيد تسوية العهدة #{data['advance_id']}:\n"
        f"قيمة العهدة: {money_line(adv_amount, currency)}\n"
        f"مصروف: {money_line(data['expense_amount'], currency)}\n"
        f"معاد: {money_line(data['returned_amount'], currency)}\n"
        f"الوصف: {desc}"
    )
    await state.set_state(WithdrawalStates.confirming_settle)
    await message.answer(summary, reply_markup=confirm_inline("settle"))


@router.callback_query(WithdrawalStates.confirming_settle, F.data == f"{CONFIRM}:settle:yes")
async def confirm_settle(callback: CallbackQuery, state: FSMContext, member: Member):
    data = await state.get_data()
    key = data.get("idempotency_key") or new_idem_key(
        "settle", data["advance_id"], data["expense_amount"], data["returned_amount"]
    )
    try:
        with get_db_context() as db:
            tx, settlement = OperationService.settle_advance(
                db=db, advance_id=data["advance_id"],
                expense_amount=data["expense_amount"],
                returned_amount=data["returned_amount"],
                description=data["description"], created_by=member.id,
                category_id=data.get("category_id"), idempotency_key=key,
            )
            tx_id = tx.id
            exp_amt = settlement.expense_amount
            ret_amt = settlement.returned_amount
            from rawafed_bot.bot.notify import notify_group_operation
            await notify_group_operation(callback.bot, db, tx)
        await state.clear()
        await callback.message.edit_text(
            f"✅ تمت تسوية العهدة\nعملية #{tx_id}\n"
            f"مصروف={exp_amt} | معاد={ret_amt}"
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
    await callback.answer()
