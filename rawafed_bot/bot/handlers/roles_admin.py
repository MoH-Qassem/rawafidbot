"""CEO role & permission administration UI."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from rawafed_bot.bot.keyboards.main_menu import BTN_ROLES, main_menu_keyboard, texts_for
from rawafed_bot.bot.states import RoleAdminStates
from rawafed_bot.database.connection import get_db_context
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.role import Permission, Role, RolePermission
from rawafed_bot.services.auth_service import AuthService
from rawafed_bot.services.permission_service import PermissionErrorDenied, PermissionService
from rawafed_bot.services.permissions_catalog import MANAGE_ROLES
from rawafed_bot.services.registration_service import RegistrationError, RegistrationService
from rawafed_bot.utils.callbacks import PERM, ROLE, pack, unpack

router = Router(name="roles_admin")


def _roles_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="عرض مصفوفة الصلاحيات", callback_data=pack(ROLE, "matrix"))],
            [InlineKeyboardButton(text="تعيين منصب لعضو", callback_data=pack(ROLE, "assign"))],
            [InlineKeyboardButton(text="إنشاء منصب", callback_data=pack(ROLE, "create"))],
            [InlineKeyboardButton(text="تعديل صلاحيات منصب", callback_data=pack(ROLE, "editperm"))],
            [InlineKeyboardButton(text="قائمة الأعضاء", callback_data=pack(ROLE, "members"))],
            [InlineKeyboardButton(text="طلبات نقل المناصب", callback_data=pack(ROLE, "transfers"))],
            [InlineKeyboardButton(text="إلغاء تسجيل عضو", callback_data=pack(ROLE, "unreg"))],
            [InlineKeyboardButton(text="إغلاق", callback_data=pack(ROLE, "close"))],
        ]
    )


def _perm_keyboard(db, rid: int) -> InlineKeyboardMarkup:
    perms = db.query(Permission).filter_by(is_active=True).order_by(Permission.id).all()
    grants = {
        rp.permission_id: rp.is_granted
        for rp in db.query(RolePermission).filter_by(role_id=rid).all()
    }
    rows = []
    for p in perms:
        on = grants.get(p.id, False)
        mark = "✅" if on else "❌"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {p.name_ar}",
            callback_data=pack(PERM, rid, p.code, 0 if on else 1),
        )])
    rows.append([InlineKeyboardButton(text="رجوع للقائمة", callback_data=pack(ROLE, "menu"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text.in_(texts_for(BTN_ROLES)))
async def roles_entry(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.member_ref import member_ids

    await state.clear()
    _, tid = member_ids(member)
    with get_db_context() as db:
        try:
            AuthService.require_permission(db, tid, MANAGE_ROLES)
        except (PermissionError, PermissionErrorDenied) as exc:
            await message.answer(str(exc))
            return
    await state.set_state(RoleAdminStates.menu)
    await message.answer("⚙️ إدارة المناصب والصلاحيات:", reply_markup=_roles_menu_kb())


@router.callback_query(F.data.startswith(f"{ROLE}:"))
async def roles_actions(callback: CallbackQuery, state: FSMContext, member: Member):
    parts = unpack(callback.data)
    action = parts[1]
    with get_db_context() as db:
        try:
            actor = AuthService.require_permission(db, member.telegram_id, MANAGE_ROLES)
        except PermissionError as exc:
            await callback.answer(str(exc)[:180], show_alert=True)
            return

        if action in {"close", "menu"}:
            if action == "close":
                await state.clear()
                await callback.message.edit_text("تم الإغلاق.")
                await callback.message.answer("القائمة:", reply_markup=main_menu_keyboard())
            else:
                await callback.message.edit_text(
                    "⚙️ إدارة المناصب والصلاحيات:",
                    reply_markup=_roles_menu_kb(),
                )
            await callback.answer()
            return

        if action == "matrix":
            matrix = PermissionService.matrix(db)
            lines = ["📋 مصفوفة الصلاحيات", "────────────"]
            for row in matrix:
                role = row["role"]
                granted = [k for k, v in row["permissions"].items() if v]
                lines.append(f"\n<b>{role.name_ar}</b> ({role.code})")
                preview = ", ".join(granted[:8]) + ("…" if len(granted) > 8 else "")
                lines.append(preview or "—")
            await callback.message.edit_text("\n".join(lines)[:4000])
            await callback.answer()
            return

        if action == "members":
            status = RegistrationService.registration_status(db)
            lines = [f"الأعضاء {status['count']}/{status['max']}"]
            for m in status["active"]:
                role = PermissionService.get_member_role(db, m.id)
                rname = role.name_ar if role else "-"
                lines.append(f"• {m.get_display_name()} — {rname}")
            await callback.message.edit_text("\n".join(lines))
            await callback.answer()
            return

        if action == "transfers":
            from rawafed_bot.database.models.role_transfer import RoleTransferRequest
            from rawafed_bot.utils.callbacks import RTREQ
            reqs = (
                db.query(RoleTransferRequest)
                .filter_by(status="pending")
                .order_by(RoleTransferRequest.id.desc())
                .limit(10)
                .all()
            )
            if not reqs:
                await callback.message.edit_text(
                    "لا توجد طلبات نقل معلّقة.",
                    reply_markup=_roles_menu_kb(),
                )
                await callback.answer()
                return
            rows = []
            lines = ["طلبات نقل المناصب المعلّقة:"]
            for req in reqs:
                role = db.query(Role).filter_by(id=req.role_id).first()
                req_m = db.query(Member).filter_by(id=req.requester_id).first()
                hold = db.query(Member).filter_by(id=req.current_holder_id).first() if req.current_holder_id else None
                lines.append(
                    f"#{req.id} {role.name_ar if role else '?'} ← "
                    f"{req_m.get_display_name() if req_m else '?'} "
                    f"(حالياً: {hold.get_display_name() if hold else '—'})"
                )
                rows.append([
                    InlineKeyboardButton(
                        text=f"✅ قبول #{req.id}",
                        callback_data=pack(RTREQ, "ok", req.id),
                    ),
                    InlineKeyboardButton(
                        text=f"❌ رفض #{req.id}",
                        callback_data=pack(RTREQ, "no", req.id),
                    ),
                ])
            rows.append([InlineKeyboardButton(text="رجوع", callback_data=pack(ROLE, "menu"))])
            await callback.message.edit_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            )
            await callback.answer()
            return

        if action == "create":
            await state.set_state(RoleAdminStates.creating_name)
            await callback.message.edit_text(
                "أرسل اسم المنصب (عربي أو إنجليزي، بحرية):\n"
                "مثال: مدقق داخلي"
            )
            await callback.answer()
            return

        if action == "assign":
            members = AuthService.get_all_members(db)
            rows = [
                [InlineKeyboardButton(
                    text=m.get_display_name()[:40],
                    callback_data=pack(ROLE, "am", m.id),
                )]
                for m in members if not m.is_ceo
            ]
            rows.append([InlineKeyboardButton(text="إلغاء", callback_data=pack(ROLE, "menu"))])
            await callback.message.edit_text(
                "اختر العضو:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            )
            await callback.answer()
            return

        if action == "am":
            mid = int(parts[2])
            roles = db.query(Role).filter_by(is_active=True).order_by(Role.id).all()
            rows = [
                [InlineKeyboardButton(
                    text=r.name_ar,
                    callback_data=pack(ROLE, "ar", mid, r.id),
                )]
                for r in roles if r.code != "ceo"
            ]
            await callback.message.edit_text(
                "اختر المنصب:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            )
            await callback.answer()
            return

        if action == "ar":
            mid, rid = int(parts[2]), int(parts[3])
            try:
                PermissionService.assign_role(db, mid, rid, actor.id)
            except PermissionErrorDenied as exc:
                await callback.answer(str(exc)[:180], show_alert=True)
                return
            await callback.message.edit_text("✅ تم تعيين المنصب.")
            await callback.answer()
            return

        if action == "editperm":
            roles = db.query(Role).filter_by(is_active=True).order_by(Role.id).all()
            rows = [
                [InlineKeyboardButton(text=r.name_ar, callback_data=pack(ROLE, "ep", r.id))]
                for r in roles
            ]
            rows.append([InlineKeyboardButton(text="رجوع", callback_data=pack(ROLE, "menu"))])
            await callback.message.edit_text(
                "اختر منصباً لتعديل صلاحياته:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            )
            await callback.answer()
            return

        if action == "ep":
            rid = int(parts[2])
            role = db.query(Role).filter_by(id=rid).one()
            await callback.message.edit_text(
                f"صلاحيات: {role.name_ar}\nاضغط للتبديل:",
                reply_markup=_perm_keyboard(db, rid),
            )
            await callback.answer()
            return

        if action == "unreg":
            members = [m for m in AuthService.get_all_members(db) if not m.is_ceo]
            rows = [
                [InlineKeyboardButton(
                    text=m.get_display_name()[:40],
                    callback_data=pack(ROLE, "ur", m.id),
                )]
                for m in members
            ]
            rows.append([InlineKeyboardButton(text="إلغاء", callback_data=pack(ROLE, "menu"))])
            await callback.message.edit_text(
                "اختر عضواً لإلغاء تسجيله (يبقى السجل المالي):",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            )
            await callback.answer()
            return

        if action == "ur":
            mid = int(parts[2])
            try:
                RegistrationService.unregister_member(db, mid, actor, "CEO unregister")
            except RegistrationError as exc:
                await callback.answer(str(exc)[:180], show_alert=True)
                return
            await callback.message.edit_text("✅ تم إلغاء التسجيل مع الاحتفاظ بالسجل.")
            await callback.answer()
            return

    await callback.answer()


@router.callback_query(F.data.startswith(f"{PERM}:"))
async def toggle_perm(callback: CallbackQuery, member: Member):
    parts = unpack(callback.data)
    rid = int(parts[1])
    code = parts[2]
    granted = parts[3] == "1"
    with get_db_context() as db:
        try:
            actor = AuthService.require_permission(db, member.telegram_id, MANAGE_ROLES)
            PermissionService.set_role_permission(db, rid, code, granted, actor)
            role = db.query(Role).filter_by(id=rid).one()
            kb = _perm_keyboard(db, rid)
            title = f"صلاحيات: {role.name_ar}\nاضغط للتبديل:"
        except (PermissionError, PermissionErrorDenied) as exc:
            await callback.answer(str(exc)[:180], show_alert=True)
            return
    await callback.message.edit_text(title, reply_markup=kb)
    await callback.answer("✅ تم التحديث")


@router.message(RoleAdminStates.creating_name)
async def create_role_name(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers import release_if_menu_button
    from rawafed_bot.bot.member_ref import member_ids, member_is_ceo

    released = await release_if_menu_button(message, state)
    if released is not None:
        return released
    name = (message.text or "").strip()
    if not name or len(name) > 80:
        await message.answer("أرسل اسماً واضحاً للمنصب (حتى 80 حرفاً).")
        return
    await state.update_data(role_name=name)
    await state.set_state(RoleAdminStates.creating_code)
    await message.answer(
        "أرسل رمزاً لاتينياً اختيارياً (مثال: auditor)\n"
        "أو اكتب <b>تخطي</b> ليُولَّد الرمز تلقائياً."
    )


@router.message(RoleAdminStates.creating_code)
async def create_role_code(message: Message, state: FSMContext, member: Member):
    from rawafed_bot.bot.helpers import release_if_menu_button
    from rawafed_bot.bot.member_ref import member_ids, member_is_ceo

    released = await release_if_menu_button(message, state)
    if released is not None:
        return released
    raw = (message.text or "").strip()
    data = await state.get_data()
    name = data.get("role_name") or "منصب"
    if raw in {"تخطي", "-", "auto", "آلي", "الي"}:
        code = PermissionService.suggest_role_code(name)
    else:
        code = raw
    _, tid = member_ids(member)
    try:
        with get_db_context() as db:
            actor = AuthService.require_permission(db, tid, MANAGE_ROLES)
            role = PermissionService.create_role(db, name, code, actor)
            role_label = f"{role.name_ar} ({role.code})"
        await state.clear()
        await message.answer(
            f"✅ تم إنشاء المنصب: {role_label}",
            reply_markup=main_menu_keyboard(is_ceo=member_is_ceo(member)),
        )
    except (PermissionError, PermissionErrorDenied) as exc:
        await message.answer(str(exc))
    except Exception as exc:
        await message.answer(f"تعذر إنشاء المنصب: {exc}")


@router.callback_query(F.data.startswith("rtr:"))
async def role_transfer_decision(callback: CallbackQuery, member: Member):
    from rawafed_bot.services.role_transfer_service import RoleTransferService
    parts = unpack(callback.data)
    decision, rid = parts[1], int(parts[2])
    with get_db_context() as db:
        try:
            actor = AuthService.require_permission(db, member.telegram_id, MANAGE_ROLES)
            if decision == "ok":
                RoleTransferService.approve(db, rid, actor)
                msg = f"✅ تمت الموافقة على طلب النقل #{rid}"
            else:
                RoleTransferService.reject(db, rid, actor)
                msg = f"تم رفض طلب النقل #{rid}"
        except (PermissionError, PermissionErrorDenied, Exception) as exc:
            await callback.answer(str(exc)[:180], show_alert=True)
            return
    await callback.message.edit_text(msg)
    await callback.answer()
