"""Contribution requests: CEO create; all pay/view."""
from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from rawafed_bot.bot.helpers import handle_cancel, money_line, new_idem_key
from rawafed_bot.bot.keyboards.common import (
    cancel_back_keyboard,
    cancel_only_keyboard,
    confirm_inline,
    contrib_menu_inline,
    currencies_inline,
    members_inline,
    obligations_inline,
    skip_inline,
)
from rawafed_bot.bot.keyboards.main_menu import (
    BTN_CONTRIB,
    BTN_CONTRIB_CREATE,
    main_menu_keyboard,
    texts_for,
)
from rawafed_bot.bot.states import ContributionStates
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.contribution import ContributionObligation
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.auth_service import AuthService
from rawafed_bot.services.contribution_service import ContributionService
from rawafed_bot.services.operation_service import OperationError
from rawafed_bot.services.query_service import QueryService
from rawafed_bot.utils.callbacks import CONFIRM, CONTRIB, CUR, MEM, OBL, SKIP, TOGGLE, pack, unpack
from rawafed_bot.utils.money import MoneyError, parse_user_amount

router = Router(name="contributions")


@router.message(F.text.in_(texts_for(BTN_CONTRIB)))
async def contrib_entry(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.bot.member_ref import member_is_ceo
    from rawafed_bot.services.permissions_catalog import PAY_CONTRIBUTION
    await state.clear()
    if not await ensure_perm(message, member, PAY_CONTRIBUTION):
        return
    await state.set_state(ContributionStates.menu)
    can_create = False
    with get_db_context() as db:
        from rawafed_bot.services.permission_service import PermissionService
        from rawafed_bot.services.permissions_catalog import CREATE_CONTRIBUTION
        m = db.query(Member).filter_by(id=member.id).first()
        can_create = bool(m and PermissionService.has_permission(db, m, CREATE_CONTRIBUTION))
    await message.answer(
        "طلبات المساهمات",
        reply_markup=main_menu_keyboard(is_ceo=member_is_ceo(member)),
    )
    await message.answer("اختر إجراءً:", reply_markup=contrib_menu_inline(can_create))


@router.message(F.text.in_(texts_for(BTN_CONTRIB_CREATE)))
async def contrib_create_entry(message: Message, state: FSMContext, member: Member):
    """Direct CEO shortcut: إضافة طلب مساهمة."""
    from rawafed_bot.bot.helpers_permissions import ensure_perm
    from rawafed_bot.services.permissions_catalog import CREATE_CONTRIBUTION

    await state.clear()
    if not await ensure_perm(message, member, CREATE_CONTRIBUTION):
        return
    with get_db_context() as db:
        currencies = QueryService.get_currencies(db)
    await state.set_state(ContributionStates.choosing_currency)
    await message.answer(
        "إنشاء طلب مساهمة — اختر العملة:",
        reply_markup=currencies_inline(currencies),
    )


@router.callback_query(F.data.startswith(f"{CONTRIB}:"))
async def contrib_menu_action(callback: CallbackQuery, state: FSMContext, member: Member):
    action = unpack(callback.data)[1]
    # Revive menu state if user tapped a stale inline button
    if action in {"list", "create", "pay"}:
        await state.set_state(ContributionStates.menu)

    if action == "list":
        with get_db_context() as db:
            requests = ContributionService.list_requests(db)
            currencies = {c.id: c for c in QueryService.get_currencies(db)}
            if not requests:
                text = "لا توجد طلبات مساهمة."
            else:
                lines = ["📋 طلبات المساهمات\n"]
                for req in requests[:20]:
                    cur = currencies.get(req.currency_id)
                    amt = money_line(req.amount, cur) if cur else str(req.amount)
                    lines.append(f"#{req.id} | {req.status} | {amt}/عضو")
                    if req.description:
                        lines.append(f"  {req.description}")
                    obs = ContributionService.get_obligations(db, req.id)
                    paid = sum(1 for o in obs if o.status == "completed")
                    lines.append(f"  مدفوع: {paid}/{len(obs)}")
                text = "\n".join(lines)
        await state.clear()
        await callback.message.edit_text(text[:4000])
        await callback.message.answer(
            "القائمة:", reply_markup=main_menu_keyboard(is_ceo=member.is_ceo)
        )
        await callback.answer()
        return

    if action == "create":
        with get_db_context() as db:
            from rawafed_bot.services.permission_service import PermissionErrorDenied, PermissionService
            from rawafed_bot.services.permissions_catalog import CREATE_CONTRIBUTION
            m = db.query(Member).filter_by(id=member.id).first()
            try:
                PermissionService.require(db, m, CREATE_CONTRIBUTION)
            except PermissionErrorDenied as exc:
                await callback.answer(str(exc), show_alert=True)
                return
            currencies = QueryService.get_currencies(db)
        await state.set_state(ContributionStates.choosing_currency)
        await callback.message.edit_text("إنشاء طلب مساهمة — اختر العملة:")
        await callback.message.answer("العملات:", reply_markup=currencies_inline(currencies))
        await callback.answer()
        return

    if action == "pay":
        with get_db_context() as db:
            obs = ContributionService.get_member_obligations(db, member.id, open_only=True)
            currencies = {c.id: c for c in QueryService.get_currencies(db)}
            items = []
            for ob in obs:
                req = ContributionService.get_request(db, ob.contribution_request_id)
                if not req:
                    continue
                cur = currencies.get(req.currency_id)
                rem = ob.amount - ob.paid_amount
                rem_txt = money_line(rem, cur) if cur else str(rem)
                items.append((ob.id, f"طلب #{req.id} — متبقي {rem_txt}"))
        if not items:
            await state.clear()
            await callback.message.edit_text("لا توجد التزامات مفتوحة عليك.")
            await callback.message.answer("القائمة:", reply_markup=main_menu_keyboard())
            await callback.answer()
            return
        await state.set_state(ContributionStates.choosing_obligation)
        await callback.message.edit_text("اختر الالتزام للدفع:")
        await callback.message.answer("الالتزامات:", reply_markup=obligations_inline(items))
        await callback.answer()
        return

    await callback.answer()


@router.callback_query(ContributionStates.choosing_currency, F.data.startswith(f"{CUR}:"))
async def create_currency(callback: CallbackQuery, state: FSMContext):
    await state.update_data(currency_id=int(unpack(callback.data)[1]), selected_members=[])
    await state.set_state(ContributionStates.entering_amount)
    await callback.message.edit_text("أدخل المبلغ لكل عضو:")
    await callback.message.answer("المبلغ:", reply_markup=cancel_back_keyboard(include_back=False))
    await callback.answer()


@router.message(ContributionStates.entering_amount)
async def create_amount(message: Message, state: FSMContext):
    if await handle_cancel(message, state):
        return
    data = await state.get_data()
    with get_db_context() as db:
        currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
        try:
            amount = parse_user_amount(message.text or "", currency)
        except MoneyError as exc:
            await message.answer(str(exc))
            return
        members = AuthService.get_all_members(db)
    await state.update_data(amount=amount)
    await state.set_state(ContributionStates.choosing_members)
    await message.answer(
        "اختر الأعضاء المشمولين:",
        reply_markup=members_inline(members, multi=True),
    )


@router.callback_query(ContributionStates.choosing_members, F.data.startswith(f"{TOGGLE}:"))
async def toggle_member(callback: CallbackQuery, state: FSMContext):
    mid = int(unpack(callback.data)[1])
    data = await state.get_data()
    selected = set(data.get("selected_members") or [])
    if mid in selected:
        selected.remove(mid)
    else:
        selected.add(mid)
    await state.update_data(selected_members=list(selected))
    with get_db_context() as db:
        members = AuthService.get_all_members(db)
    await callback.message.edit_reply_markup(
        reply_markup=members_inline(members, selected=selected, multi=True)
    )
    await callback.answer()


@router.callback_query(ContributionStates.choosing_members, F.data == pack(MEM, "done"))
async def members_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_members") or []
    if not selected:
        await callback.answer("اختر عضواً واحداً على الأقل", show_alert=True)
        return
    await state.set_state(ContributionStates.entering_description)
    await callback.message.edit_text(f"تم اختيار {len(selected)} عضو/أعضاء.")
    await callback.message.answer(
        "أدخل وصف الطلب (أو - للتخطي):",
        reply_markup=cancel_back_keyboard(include_back=False),
    )
    await callback.answer()


@router.message(ContributionStates.entering_description)
async def create_description(message: Message, state: FSMContext):
    if await handle_cancel(message, state):
        return
    desc = (message.text or "").strip()
    if desc in {"-", "تخطي"}:
        desc = None
    await state.update_data(description=desc)
    await state.set_state(ContributionStates.entering_due_date)
    await message.answer(
        "أدخل تاريخ الاستحقاق YYYY-MM-DD أو تخطي:",
        reply_markup=skip_inline(),
    )


@router.callback_query(ContributionStates.entering_due_date, F.data.startswith(f"{SKIP}:"))
async def skip_due_date(callback: CallbackQuery, state: FSMContext):
    await state.update_data(due_date=None)
    await _show_create_summary(callback, state)
    await callback.answer()


@router.message(ContributionStates.entering_due_date)
async def create_due_date(message: Message, state: FSMContext):
    if await handle_cancel(message, state):
        return
    raw = (message.text or "").strip()
    try:
        due = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        await message.answer("صيغة التاريخ غير صحيحة. استخدم YYYY-MM-DD أو تخطي.")
        return
    await state.update_data(due_date=due.isoformat())
    # reuse summary via fake callback-like path
    data = await state.get_data()
    with get_db_context() as db:
        currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
        members = {m.id: m for m in AuthService.get_all_members(db)}
        names = ", ".join(
            members[i].get_display_name()
            for i in data.get("selected_members") or []
            if i in members
        )
        amount_txt = money_line(data["amount"], currency)
    due_txt = due.strftime("%Y-%m-%d")
    await state.set_state(ContributionStates.confirming_create)
    await message.answer(
        "ملخص طلب المساهمة:\n"
        f"المبلغ/عضو: {amount_txt}\n"
        f"الأعضاء: {names}\n"
        f"الوصف: {data.get('description') or '—'}\n"
        f"الاستحقاق: {due_txt}\n"
        "تأكيد الإنشاء؟",
        reply_markup=confirm_inline("contrib_create"),
    )


async def _show_create_summary(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    with get_db_context() as db:
        currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
        members = {m.id: m for m in AuthService.get_all_members(db)}
        names = ", ".join(
            members[i].get_display_name()
            for i in data.get("selected_members") or []
            if i in members
        )
        amount_txt = money_line(data["amount"], currency)
    due = data.get("due_date")
    due_txt = due[:10] if isinstance(due, str) and due else "بدون"
    await state.set_state(ContributionStates.confirming_create)
    text = (
        "ملخص طلب المساهمة:\n"
        f"المبلغ/عضو: {amount_txt}\n"
        f"الأعضاء: {names}\n"
        f"الوصف: {data.get('description') or '—'}\n"
        f"الاستحقاق: {due_txt}\n"
        "تأكيد الإنشاء؟"
    )
    try:
        await callback.message.edit_text(text)
    except Exception:
        pass
    await callback.message.answer("تأكيد:", reply_markup=confirm_inline("contrib_create"))


@router.callback_query(
    ContributionStates.confirming_create,
    F.data == pack(CONFIRM, "contrib_create", "yes"),
)
async def create_confirm(callback: CallbackQuery, state: FSMContext, member: Member):
    data = await state.get_data()
    due_raw = data.get("due_date")
    due = datetime.fromisoformat(due_raw) if isinstance(due_raw, str) and due_raw else None
    key = new_idem_key(
        "contrib_req", member.id, data["currency_id"], data["amount"],
        sorted(data.get("selected_members") or []),
    )
    try:
        with get_db_context() as db:
            AuthService.require_ceo(db, member.telegram_id)
            currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
            req = ContributionService.create_request(
                db=db,
                amount_per_member=data["amount"],
                currency_id=data["currency_id"],
                member_ids=list(data.get("selected_members") or []),
                created_by_telegram_id=member.telegram_id,
                description=data.get("description"),
                due_date=due,
                idempotency_key=key,
            )
            amount_txt = money_line(req.amount, currency)
            req_id = req.id
        await state.clear()
        await callback.message.edit_text(
            f"✅ تم إنشاء طلب المساهمة #{req_id}\nالمبلغ لكل عضو: {amount_txt}"
        )
        await callback.message.answer("القائمة:", reply_markup=main_menu_keyboard())
    except PermissionError as exc:
        await state.clear()
        await callback.message.answer(str(exc), reply_markup=main_menu_keyboard())
    except OperationError as exc:
        await state.clear()
        await callback.message.answer(f"فشل الإنشاء: {exc}", reply_markup=main_menu_keyboard())
    except Exception:
        await state.clear()
        await callback.message.answer("حدث خطأ غير متوقع.", reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(ContributionStates.choosing_obligation, F.data.startswith(f"{OBL}:"))
async def choose_obligation(callback: CallbackQuery, state: FSMContext):
    obl_id = int(unpack(callback.data)[1])
    with get_db_context() as db:
        ob = db.query(ContributionObligation).filter_by(id=obl_id).first()
        if not ob:
            await callback.answer("الالتزام غير موجود", show_alert=True)
            return
        req = ContributionService.get_request(db, ob.contribution_request_id)
        currency = db.query(Currency).filter_by(id=req.currency_id).first()
        remaining = ob.amount - ob.paid_amount
        rem_txt = money_line(remaining, currency)
        request_id = req.id
        await state.update_data(
            obligation_id=ob.id,
            currency_id=req.currency_id,
            remaining=remaining,
            request_id=request_id,
        )
    await state.set_state(ContributionStates.entering_pay_amount)
    await callback.message.edit_text(f"التزام طلب #{request_id} — المتبقي: {rem_txt}")
    await callback.message.answer("أدخل مبلغ الدفع:", reply_markup=cancel_back_keyboard(include_back=False))
    await callback.answer()


@router.message(ContributionStates.entering_pay_amount)
async def pay_amount(message: Message, state: FSMContext):
    if await handle_cancel(message, state):
        return
    data = await state.get_data()
    with get_db_context() as db:
        currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
        try:
            amount = parse_user_amount(message.text or "", currency)
        except MoneyError as exc:
            await message.answer(str(exc))
            return
        amount_txt = money_line(amount, currency)
    if amount > data.get("remaining", 0):
        await message.answer("المبلغ أكبر من المتبقي.")
        return
    await state.update_data(amount=amount)
    await state.set_state(ContributionStates.confirming_pay)
    await message.answer(
        f"ملخص دفع المساهمة (طلب #{data.get('request_id')}):\n"
        f"المبلغ: {amount_txt}\n"
        "تأكيد؟",
        reply_markup=confirm_inline("contrib_pay"),
    )


@router.callback_query(
    ContributionStates.confirming_pay,
    F.data == pack(CONFIRM, "contrib_pay", "yes"),
)
async def pay_confirm(callback: CallbackQuery, state: FSMContext, member: Member):
    data = await state.get_data()
    key = new_idem_key("contrib_pay", data["obligation_id"], data["amount"], member.id)
    try:
        with get_db_context() as db:
            currency = db.query(Currency).filter_by(id=data["currency_id"]).first()
            tx = ContributionService.pay_obligation(
                db=db,
                obligation_id=data["obligation_id"],
                amount=data["amount"],
                created_by=member.id,
                description=f"دفع مساهمة طلب #{data.get('request_id')}",
                idempotency_key=key,
            )
            amount_txt = money_line(tx.amount, currency)
            tx_id = tx.id
        await state.clear()
        await callback.message.edit_text(
            f"✅ تم الدفع\nرقم العملية: #{tx_id}\nالمبلغ: {amount_txt}"
        )
        await callback.message.answer("القائمة:", reply_markup=main_menu_keyboard())
    except OperationError as exc:
        await state.clear()
        await callback.message.answer(f"فشل الدفع: {exc}", reply_markup=main_menu_keyboard())
    except Exception:
        await state.clear()
        await callback.message.answer("حدث خطأ غير متوقع.", reply_markup=main_menu_keyboard())
    await callback.answer()
