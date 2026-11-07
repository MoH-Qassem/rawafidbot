"""Debts listing and repayment."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from rawafed_bot.bot.helpers import handle_cancel, money_line, new_idem_key
from rawafed_bot.bot.keyboards.common import cancel_back_keyboard, confirm_inline, debts_inline
from rawafed_bot.bot.keyboards.main_menu import BTN_DEBTS, main_menu_keyboard, texts_for
from rawafed_bot.bot.states import DebtStates
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.debt import MemberDebt
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.operation_service import OperationError, OperationService
from rawafed_bot.services.query_service import QueryService
from rawafed_bot.services.report_service import ReportService
from rawafed_bot.utils.callbacks import CONFIRM, DEBT, unpack
from rawafed_bot.utils.money import MoneyError, format_amount, parse_user_amount

router = Router(name="debts")


@router.message(F.text.in_(texts_for(BTN_DEBTS)))
async def show_debts(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.services.permissions_catalog import VIEW_DEBTS
    if not await ensure_perm(message, member, VIEW_DEBTS):
        return
    await state.clear()
    with get_db_context() as db:
        text = ReportService.debts_report(db)
        debts = QueryService.active_debts(db)
        items = []
        for d in debts:
            member = db.query(Member).filter_by(id=d.member_id).first()
            currency = db.query(Currency).filter_by(id=d.currency_id).first()
            items.append((
                d.id,
                f"#{d.id} {member.get_display_name() if member else d.member_id} — {format_amount(d.remaining, currency)}",
            ))
    await message.answer(text, reply_markup=main_menu_keyboard(is_ceo=member.is_ceo))
    if items:
        await state.set_state(DebtStates.choosing_debt)
        await message.answer("لتسديد دين اختر من القائمة:", reply_markup=debts_inline(items))


@router.callback_query(DebtStates.choosing_debt, F.data.startswith(f"{DEBT}:"))
async def choose_debt(callback: CallbackQuery, state: FSMContext):
    debt_id = int(unpack(callback.data)[1])
    await state.update_data(debt_id=debt_id)
    await state.set_state(DebtStates.entering_amount)
    await callback.message.edit_text("أدخل مبلغ التسديد:")
    await callback.message.answer("المبلغ:", reply_markup=cancel_back_keyboard(include_back=False))
    await callback.answer()


@router.message(DebtStates.entering_amount)
async def enter_amount(message: Message, state: FSMContext):
    if await handle_cancel(message, state):
        return
    data = await state.get_data()
    with get_db_context() as db:
        debt = db.query(MemberDebt).filter_by(id=data["debt_id"]).first()
        if not debt:
            await message.answer("الدين غير موجود.", reply_markup=main_menu_keyboard())
            await state.clear()
            return
        currency = db.query(Currency).filter_by(id=debt.currency_id).first()
        try:
            amount = parse_user_amount(message.text, currency)
        except MoneyError as exc:
            await message.answer(str(exc))
            return
        if amount > debt.remaining:
            await message.answer("المبلغ أكبر من المتبقي.")
            return
        await state.update_data(
            amount=amount, currency_id=debt.currency_id, member_id=debt.member_id,
            remaining=debt.remaining,
        )
    await state.set_state(DebtStates.entering_description)
    await message.answer("أدخل وصف التسديد:", reply_markup=cancel_back_keyboard(include_back=False))


@router.message(DebtStates.entering_description)
async def enter_description(message: Message, state: FSMContext):
    if await handle_cancel(message, state):
        return
    desc = (message.text or "").strip() or "تسديد مستحقات"
    data = await state.get_data()
    key = new_idem_key("debt", data["debt_id"], data["amount"])
    await state.update_data(description=desc, idempotency_key=key)
    with get_db_context() as db:
        currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
    summary = (
        f"تأكيد تسديد الدين #{data['debt_id']}:\n"
        f"المبلغ: {money_line(data['amount'], currency)}\n"
        f"المتبقي قبل التسديد: {money_line(data['remaining'], currency)}\n"
        f"الوصف: {desc}"
    )
    await state.set_state(DebtStates.confirming)
    await message.answer(summary, reply_markup=confirm_inline("debt"))


@router.callback_query(DebtStates.confirming, F.data == f"{CONFIRM}:debt:yes")
async def confirm_repay(callback: CallbackQuery, state: FSMContext, member: Member):
    data = await state.get_data()
    key = data.get("idempotency_key") or new_idem_key("debt", data["debt_id"], data["amount"])
    try:
        with get_db_context() as db:
            tx = OperationService.record_debt_repayment(
                db=db, amount=data["amount"], currency_id=data["currency_id"],
                member_id=data["member_id"], description=data["description"],
                created_by=member.id, debt_id=data["debt_id"], idempotency_key=key,
            )
            currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
            txt = money_line(tx.amount, currency)
            tx_id = tx.id
            from rawafed_bot.bot.notify import notify_group_operation
            await notify_group_operation(callback.bot, db, tx)
        await state.clear()
        await callback.message.edit_text(f"✅ تم التسديد #{tx_id}\nالمبلغ: {txt}")
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
