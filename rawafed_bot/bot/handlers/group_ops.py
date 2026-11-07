"""Natural-language financial operations entirely inside the company group."""
from __future__ import annotations

import logging
import secrets
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from rawafed_bot.bot.keyboards.main_menu import main_menu_keyboard
from rawafed_bot.bot.notify import notify_group_operation
from rawafed_bot.bot.states import GroupOpStates
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.expense_category import ExpenseCategory
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.nl_operation_parser import NLOperationParser, ParsedOperation
from rawafed_bot.services.operation_service import OperationError, OperationService
from rawafed_bot.services.permission_service import PermissionService
from rawafed_bot.services.permissions_catalog import (
    RECORD_DEPOSIT,
    RECORD_EXPENSE,
    RECORD_WITHDRAWAL,
    VIEW_DEBTS,
)
from rawafed_bot.services.query_service import QueryService
from rawafed_bot.utils.callbacks import CAT, CUR, GOP, pack, unpack
from rawafed_bot.utils.idempotency import generate_idempotency_key
from rawafed_bot.utils.money import MoneyError, find_currency, format_amount, parse_user_amount

logger = logging.getLogger(__name__)
router = Router(name="group_ops")

PERM_BY_OP = {
    "expense": RECORD_EXPENSE,
    "deposit": RECORD_DEPOSIT,
    "withdrawal": RECORD_WITHDRAWAL,
    "debt_repay": VIEW_DEBTS,
}

ASK_AR = {
    "amount": "ما المبلغ؟",
    "currency": "ما العملة؟ (دولار / ليرة سورية / ليرة تركية)",
    "description": "ما وصف العملية؟",
    "category": "ما تصنيف المصروف؟",
    "op_type": "ما نوع العملية؟ (مصروف / إيداع / سحب)",
}


def _confirm_kb(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تأكيد العملية", callback_data=pack(GOP, "yes", token)),
                InlineKeyboardButton(text="❌ إلغاء", callback_data=pack(GOP, "no", token)),
            ]
        ]
    )


def _currencies_kb() -> InlineKeyboardMarkup:
    with get_db_context() as db:
        curs = QueryService.get_currencies(db)
        rows = [
            [InlineKeyboardButton(text=c.name_ar, callback_data=pack(GOP, "cur", c.id))]
            for c in curs
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _categories_kb() -> InlineKeyboardMarkup:
    with get_db_context() as db:
        cats = db.query(ExpenseCategory).filter_by(is_active=True).order_by(ExpenseCategory.id).all()
        rows = [
            [InlineKeyboardButton(text=c.name, callback_data=pack(GOP, "cat", c.id))]
            for c in cats
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def start_group_operation(
    message: Message,
    state: FSMContext,
    member: Member,
    parsed: ParsedOperation,
) -> None:
    """Entry from group intelligence when a write intent is detected."""
    mention = f'<a href="tg://user?id={member.telegram_id}">{member.display_name or member.telegram_full_name or "عضو"}</a>'
    token = secrets.token_hex(4)
    data = {
        "token": token,
        "owner_tg_id": member.telegram_id,
        "owner_member_id": member.id,
        "source_message_id": message.message_id,
        "chat_id": message.chat.id,
        "op_type": parsed.op_type,
        "amount_text": parsed.amount_text,
        "amount_minor": parsed.amount_minor,
        "currency_id": parsed.currency_id,
        "currency_code": parsed.currency_code,
        "description": parsed.description,
        "category_id": parsed.category_id,
        "category_name": parsed.category_name,
        "confirmed": False,
    }
    await state.clear()
    await state.update_data(gop=data)

    missing = list(parsed.missing)
    # Permission gate early
    with get_db_context() as db:
        m = db.query(Member).filter_by(id=member.id).first()
        code = PERM_BY_OP.get(parsed.op_type or "")
        if code and not PermissionService.has_permission(db, m, code):
            await message.reply(f"{mention}\n⛔ ليست لديك صلاحية تنفيذ هذه العملية.")
            await state.clear()
            return

    if missing:
        field = missing[0]
        await state.set_state(GroupOpStates.collecting)
        await state.update_data(gop_missing=missing, gop_ask=field)
        if field == "currency":
            await message.reply(f"{mention}\n{ASK_AR[field]}", reply_markup=_currencies_kb())
        elif field == "category":
            await message.reply(f"{mention}\n{ASK_AR[field]}", reply_markup=_categories_kb())
        else:
            await message.reply(f"{mention}\n{ASK_AR.get(field, 'أكمل البيانات:')}")
        return

    await _show_confirm(message, state, member, data)


async def _show_confirm(message: Message, state: FSMContext, member: Member, data: dict):
    parsed = ParsedOperation(
        op_type=data.get("op_type"),
        amount_text=data.get("amount_text"),
        amount_minor=data.get("amount_minor"),
        currency_id=data.get("currency_id"),
        currency_code=data.get("currency_code"),
        description=data.get("description"),
        category_id=data.get("category_id"),
        category_name=data.get("category_name"),
    )
    name = member.get_display_name()
    summary = NLOperationParser.summary_ar(parsed, name)
    await state.set_state(GroupOpStates.confirming)
    await state.update_data(gop=data)
    await message.reply(summary, reply_markup=_confirm_kb(data["token"]))


def _apply_field(data: dict, field: str, value, db=None) -> list:
    """Update data from collected answer; return remaining missing fields."""
    if field == "amount":
        data["amount_text"] = str(value).strip()
        if data.get("currency_id") and db is not None:
            cur = db.query(Currency).filter_by(id=data["currency_id"]).first()
            try:
                data["amount_minor"] = parse_user_amount(data["amount_text"], cur)
            except MoneyError:
                data["amount_minor"] = None
    elif field == "currency":
        if isinstance(value, int):
            data["currency_id"] = value
            if db is not None:
                cur = db.query(Currency).filter_by(id=value).first()
                data["currency_code"] = cur.code if cur else None
        else:
            if db is not None:
                cur = find_currency(db, str(value))
                if cur:
                    data["currency_id"] = cur.id
                    data["currency_code"] = cur.code
        if data.get("amount_text") and data.get("currency_id") and db is not None:
            cur = db.query(Currency).filter_by(id=data["currency_id"]).first()
            try:
                data["amount_minor"] = parse_user_amount(data["amount_text"], cur)
            except MoneyError:
                data["amount_minor"] = None
    elif field == "description":
        data["description"] = str(value).strip()[:200]
    elif field == "category":
        if isinstance(value, int):
            data["category_id"] = value
            if db is not None:
                cat = db.query(ExpenseCategory).filter_by(id=value).first()
                data["category_name"] = cat.name if cat else None
        else:
            data["category_name"] = str(value).strip()
            if db is not None:
                cat = db.query(ExpenseCategory).filter_by(name=data["category_name"]).first()
                if cat:
                    data["category_id"] = cat.id
    elif field == "op_type":
        raw = str(value)
        data["op_type"] = NLOperationParser.detect_type(raw) or data.get("op_type")

    missing = []
    if not data.get("op_type"):
        missing.append("op_type")
    if not data.get("amount_text") or not data.get("amount_minor"):
        missing.append("amount")
    if not data.get("currency_id"):
        missing.append("currency")
    if data.get("op_type") == "expense" and not data.get("category_id"):
        missing.append("category")
    if not data.get("description"):
        missing.append("description")
    return missing


@router.message(GroupOpStates.collecting, F.text)
async def collect_missing(message: Message, state: FSMContext, member: Member = None):
    if not message.from_user:
        return
    data_all = await state.get_data()
    gop = data_all.get("gop") or {}
    if gop.get("owner_tg_id") and gop["owner_tg_id"] != message.from_user.id:
        return  # ignore other members' replies
    field = data_all.get("gop_ask")
    if not field:
        return
    with get_db_context() as db:
        missing = _apply_field(gop, field, message.text, db)
    await state.update_data(gop=gop, gop_missing=missing)
    mention = f'<a href="tg://user?id={message.from_user.id}">{message.from_user.full_name}</a>'
    if missing:
        nxt = missing[0]
        await state.update_data(gop_ask=nxt)
        if nxt == "currency":
            await message.reply(f"{mention}\n{ASK_AR[nxt]}", reply_markup=_currencies_kb())
        elif nxt == "category":
            await message.reply(f"{mention}\n{ASK_AR[nxt]}", reply_markup=_categories_kb())
        else:
            await message.reply(f"{mention}\n{ASK_AR.get(nxt, 'أكمل:')}")
        return
    # done collecting
    mem = member
    if not mem:
        with get_db_context() as db:
            mem = db.query(Member).filter_by(telegram_id=message.from_user.id, is_active=True).first()
            if mem:
                db.expunge(mem)
    if not mem:
        await message.reply("يجب أن تكون مسجّلاً.")
        await state.clear()
        return
    await _show_confirm(message, state, mem, gop)


@router.callback_query(GroupOpStates.collecting, F.data.startswith(f"{GOP}:cur:"))
@router.callback_query(GroupOpStates.collecting, F.data.startswith(f"{GOP}:cat:"))
async def collect_via_button(callback: CallbackQuery, state: FSMContext, member: Member = None):
    parts = unpack(callback.data)
    data_all = await state.get_data()
    gop = data_all.get("gop") or {}
    if gop.get("owner_tg_id") and callback.from_user and gop["owner_tg_id"] != callback.from_user.id:
        await callback.answer("هذه العملية لعضو آخر", show_alert=True)
        return
    kind = parts[1]
    value = int(parts[2])
    field = "currency" if kind == "cur" else "category"
    with get_db_context() as db:
        missing = _apply_field(gop, field, value, db)
    await state.update_data(gop=gop, gop_missing=missing)
    await callback.answer()
    if missing:
        nxt = missing[0]
        await state.update_data(gop_ask=nxt)
        text = ASK_AR.get(nxt, "أكمل:")
        if nxt == "currency":
            await callback.message.answer(text, reply_markup=_currencies_kb())
        elif nxt == "category":
            await callback.message.answer(text, reply_markup=_categories_kb())
        else:
            await callback.message.answer(text)
        return
    mem = member
    if not mem and callback.from_user:
        with get_db_context() as db:
            mem = db.query(Member).filter_by(telegram_id=callback.from_user.id, is_active=True).first()
            if mem:
                db.expunge(mem)
    if mem:
        await _show_confirm(callback.message, state, mem, gop)


@router.callback_query(F.data.startswith(f"{GOP}:"))
async def confirm_group_op(callback: CallbackQuery, state: FSMContext, member: Member = None, bot: Bot = None):
    parts = unpack(callback.data)
    if len(parts) < 3:
        await callback.answer()
        return
    action, token = parts[1], parts[2]
    if action not in {"yes", "no"}:
        return  # cur/cat handled elsewhere

    data_all = await state.get_data()
    gop = data_all.get("gop") or {}
    if gop.get("token") != token:
        await callback.answer("انتهت صلاحية هذا الطلب أو تم تنفيذه.", show_alert=True)
        return
    if not callback.from_user or callback.from_user.id != gop.get("owner_tg_id"):
        await callback.answer("⛔ لا يمكنك تأكيد عملية بدأها عضو آخر.", show_alert=True)
        return
    if action == "no":
        await state.clear()
        await callback.message.edit_text("تم إلغاء العملية.")
        await callback.answer("أُلغيت")
        return
    if gop.get("confirmed"):
        await callback.answer("تم تنفيذ هذه العملية مسبقاً.", show_alert=True)
        return

    gop["confirmed"] = True
    await state.update_data(gop=gop)

    idem = generate_idempotency_key(
        "gop",
        str(gop.get("owner_member_id")),
        str(gop.get("source_message_id")),
        str(gop.get("op_type")),
        str(gop.get("amount_minor")),
        str(gop.get("currency_id")),
        str(gop.get("description")),
        token,
    )

    try:
        with get_db_context() as db:
            mid = gop["owner_member_id"]
            m = db.query(Member).filter_by(id=mid, is_active=True).first()
            if not m:
                raise OperationError("العضو غير نشط.")
            op = gop["op_type"]
            amount = int(gop["amount_minor"])
            cid = int(gop["currency_id"])
            desc = gop.get("description") or op
            if op == "expense":
                cat_id = int(gop["category_id"])
                tx = OperationService.record_expense_from_box(
                    db, amount, cid, cat_id, mid, desc, mid, idem
                )
            elif op == "deposit":
                tx = OperationService.record_deposit(
                    db, amount, cid, mid, desc, mid, idem
                )
            elif op == "withdrawal":
                tx = OperationService.record_withdrawal(
                    db, amount, cid, mid, desc, mid, idem
                )
            else:
                raise OperationError("نوع العملية غير مدعوم من المجموعة حالياً.")

            currency = db.query(Currency).filter_by(id=cid).first()
            from rawafed_bot.database.models.account import Account
            cash = db.query(Account).filter_by(account_type="cash_box", currency_id=cid).first()
            amt_txt = format_amount(tx.amount, currency)
            bal_txt = format_amount(cash.balance, currency) if cash else "—"
            cat_name = gop.get("category_name") or "—"
            tx_id = tx.id
            await notify_group_operation(callback.bot, db, tx)
            success = (
                f"✅ تم تسجيل العملية بنجاح.\n\n"
                f"رقم العملية: #{tx_id}\n"
                f"المبلغ: {amt_txt}\n"
            )
            if op == "expense":
                success += f"التصنيف: {cat_name}\n"
            success += (
                f"الوصف: {desc}\n"
                f"المنفذ: {m.get_display_name()}\n"
                f"رصيد الصندوق الجديد: {bal_txt}"
            )
        await state.clear()
        await callback.message.edit_text(success)
        await callback.message.answer(
            "القائمة:",
            reply_markup=main_menu_keyboard(is_ceo=bool(member and member.is_ceo)),
        )
        await callback.answer("تم")
    except OperationError as exc:
        await state.clear()
        await callback.message.edit_text(str(exc))
        await callback.answer()
    except Exception:
        logger.exception("group op failed")
        await state.clear()
        await callback.message.edit_text("تعذر حفظ العملية.")
        await callback.answer()
