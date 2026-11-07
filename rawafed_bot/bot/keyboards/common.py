"""Shared reply/inline keyboards."""
from __future__ import annotations

from typing import Iterable, Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.expense_category import ExpenseCategory
from rawafed_bot.database.models.member import Member
from rawafed_bot.utils.callbacks import (
    ADV,
    CAT,
    CONFIRM,
    CONTRIB,
    CUR,
    DEBT,
    EXP_MODE,
    MEM,
    OBL,
    REPORT,
    SETTINGS,
    SKIP,
    TOGGLE,
    WD_MODE,
    pack,
)

BTN_CANCEL = "إلغاء"
BTN_BACK = "رجوع"
BTN_SKIP = "تخطي"


def cancel_back_keyboard(include_back: bool = True) -> ReplyKeyboardMarkup:
    row = [KeyboardButton(text=BTN_CANCEL)]
    if include_back:
        row.insert(0, KeyboardButton(text=BTN_BACK))
    return ReplyKeyboardMarkup(keyboard=[row], resize_keyboard=True)


def cancel_only_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )


def confirm_inline(prefix: str = "ok") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تأكيد", callback_data=pack(CONFIRM, prefix, "yes")),
                InlineKeyboardButton(text="❌ إلغاء", callback_data=pack(CONFIRM, prefix, "no")),
            ]
        ]
    )


def currencies_inline(currencies: Sequence[Currency]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{c.name_ar} ({c.code})", callback_data=pack(CUR, c.id))]
        for c in currencies
    ]
    rows.append([InlineKeyboardButton(text="إلغاء", callback_data=pack(CONFIRM, "flow", "no"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def categories_inline(categories: Sequence[ExpenseCategory]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=cat.name, callback_data=pack(CAT, cat.id))]
        for cat in categories
    ]
    rows.append([InlineKeyboardButton(text="إلغاء", callback_data=pack(CONFIRM, "flow", "no"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def expense_mode_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="من الصندوق (شركة)", callback_data=pack(EXP_MODE, "box"))],
            [InlineKeyboardButton(
                text="على سجل العضو (يدين الصندوق)",
                callback_data=pack(EXP_MODE, "personal"),
            )],
            [InlineKeyboardButton(text="إلغاء", callback_data=pack(CONFIRM, "flow", "no"))],
        ]
    )


def withdrawal_mode_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="سحب نهائي من الحقوق", callback_data=pack(WD_MODE, "final"))],
            [InlineKeyboardButton(text="عهدة (سلفة)", callback_data=pack(WD_MODE, "advance"))],
            [InlineKeyboardButton(text="تسوية عهدة مفتوحة", callback_data=pack(WD_MODE, "settle"))],
            [InlineKeyboardButton(text="إلغاء", callback_data=pack(CONFIRM, "flow", "no"))],
        ]
    )


def members_inline(
    members: Sequence[Member],
    selected: Iterable[int] = (),
    multi: bool = False,
) -> InlineKeyboardMarkup:
    selected_set = set(selected)
    rows = []
    for m in members:
        mark = "✅ " if m.id in selected_set else ""
        label = f"{mark}{m.get_display_name()}"
        action = TOGGLE if multi else MEM
        rows.append([InlineKeyboardButton(text=label, callback_data=pack(action, m.id))])
    if multi:
        rows.append([InlineKeyboardButton(text="✔️ تم الاختيار", callback_data=pack(MEM, "done"))])
    rows.append([InlineKeyboardButton(text="إلغاء", callback_data=pack(CONFIRM, "flow", "no"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def debts_inline(items: Sequence[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=pack(DEBT, debt_id))] for debt_id, label in items]
    rows.append([InlineKeyboardButton(text="إلغاء", callback_data=pack(CONFIRM, "flow", "no"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def advances_inline(items: Sequence[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=pack(ADV, adv_id))] for adv_id, label in items]
    rows.append([InlineKeyboardButton(text="إلغاء", callback_data=pack(CONFIRM, "flow", "no"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def contributions_inline(items: Sequence[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=pack(CONTRIB, req_id))] for req_id, label in items]
    rows.append([InlineKeyboardButton(text="إلغاء", callback_data=pack(CONFIRM, "flow", "no"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def obligations_inline(items: Sequence[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=pack(OBL, obl_id))] for obl_id, label in items]
    rows.append([InlineKeyboardButton(text="إلغاء", callback_data=pack(CONFIRM, "flow", "no"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def contrib_menu_inline(is_ceo: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="عرض الطلبات", callback_data=pack(CONTRIB, "list"))],
        [InlineKeyboardButton(text="دفع التزاماتي", callback_data=pack(CONTRIB, "pay"))],
    ]
    if is_ceo:
        rows.insert(0, [InlineKeyboardButton(text="إنشاء طلب مساهمة", callback_data=pack(CONTRIB, "create"))])
    rows.append([InlineKeyboardButton(text="إغلاق", callback_data=pack(CONFIRM, "flow", "no"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reports_menu_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="حالة الصندوق", callback_data=pack(REPORT, "cash"))],
            [InlineKeyboardButton(text="مصروفات حسب التصنيف", callback_data=pack(REPORT, "exp"))],
            [InlineKeyboardButton(text="ملخص أسبوعي", callback_data=pack(REPORT, "week"))],
            [InlineKeyboardButton(text="ملخص شهري", callback_data=pack(REPORT, "month"))],
            [InlineKeyboardButton(text="إغلاق", callback_data=pack(CONFIRM, "flow", "no"))],
        ]
    )


def settings_menu_inline(is_ceo: bool = False, show_backup: bool = None) -> InlineKeyboardMarkup:
    if show_backup is None:
        show_backup = is_ceo
    rows = [
        [InlineKeyboardButton(text="عرض ملفّي", callback_data=pack(SETTINGS, "profile"))],
        [InlineKeyboardButton(text="تعديل بياناتي", callback_data=pack(SETTINGS, "edit"))],
        [InlineKeyboardButton(text="تعديل الاسم الظاهر", callback_data=pack(SETTINGS, "name"))],
        [InlineKeyboardButton(text="تعديل المسمى الوظيفي", callback_data=pack(SETTINGS, "title"))],
    ]
    if show_backup:
        rows.append(
            [InlineKeyboardButton(text="نسخ احتياطي", callback_data=pack(SETTINGS, "backup"))]
        )
    rows.append([InlineKeyboardButton(text="إغلاق", callback_data=pack(CONFIRM, "flow", "no"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def skip_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="تخطي", callback_data=pack(SKIP, "1"))],
            [InlineKeyboardButton(text="إلغاء", callback_data=pack(CONFIRM, "flow", "no"))],
        ]
    )
