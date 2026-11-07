"""Single main reply keyboard — MENU_VERSION menu-v3-group-first."""
from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from rawafed_bot.core.version import MENU_VERSION

# --- Canonical button labels (v3) ---
BTN_CASHBOX = "💰 حالة الصندوق"
BTN_EXPENSE = "➖ تسجيل مصروف"
BTN_DEPOSIT = "➕ تسجيل إيداع"
BTN_WITHDRAW = "💳 تسجيل سحب"
BTN_HISTORY = "📒 سجل العمليات"

BTN_MEMBERS = "👥 حسابات الأعضاء"
BTN_CONTRIB = "🤝 طلبات المساهمات"
BTN_DEBTS = "💸 الديون والمستحقات"
# Deprecated label kept so old Telegram keyboards still get a polite reply
BTN_ADVANCES = "📦 العهد المالية"

BTN_REPORT = "📊 التقرير المالي"
BTN_MONTHLY = "📅 التقرير الشهري"
BTN_WEEKLY = "📆 التقرير الأسبوعي"
BTN_EXPORT = "📥 تصدير Excel"

BTN_MY_PROFILE = "👤 ملفي الشخصي"
BTN_ROLES = "🏢 إدارة المناصب والصلاحيات"
BTN_SETTINGS = "⚙️ الإعدادات"

BTN_GUIDE = "📖 دليل الاستخدام والمزايا"
BTN_MAIN = "🏠 القائمة الرئيسية"

# Backwards-compatible aliases (old reply keyboards cached by Telegram clients)
LEGACY = {
    BTN_HISTORY: {"📋 سجل العمليات", "سجل العمليات"},
    BTN_DEBTS: {"📒 الديون والمستحقات", "الديون والمستحقات"},
    BTN_CONTRIB: {"🤝 المساهمات والعهد", "طلبات المساهمات", "المساهمات والعهد", "🤝 طلبات المساهمات"},
    BTN_REPORT: {"📊 التقارير المالية", "التقارير المالية"},
    BTN_EXPORT: {"📁 تصدير Excel", "تصدير Excel"},
    BTN_ROLES: {"🏢 المناصب والصلاحيات", "إدارة المناصب", "صلاحيات الأعضاء"},
    BTN_GUIDE: {"دليل الاستخدام"},
}


def texts_for(*canonical: str) -> set[str]:
    """Canonical label + legacy aliases for filter matching."""
    out: set[str] = set()
    for c in canonical:
        out.add(c)
        out |= LEGACY.get(c, set())
    return out


# Aliases used by older imports/tests
BTN_REPORTS = BTN_REPORT


def all_member_buttons() -> list[str]:
    return [
        BTN_CASHBOX, BTN_EXPENSE, BTN_DEPOSIT, BTN_WITHDRAW, BTN_HISTORY,
        BTN_MEMBERS, BTN_CONTRIB, BTN_DEBTS,
        BTN_REPORT, BTN_MONTHLY, BTN_WEEKLY, BTN_EXPORT,
        BTN_MY_PROFILE, BTN_SETTINGS,
        BTN_GUIDE, BTN_MAIN,
    ]


def all_ceo_buttons() -> list[str]:
    buttons = all_member_buttons()
    # Insert roles before settings block end — after profile/settings section
    idx = buttons.index(BTN_SETTINGS)
    return buttons[:idx] + [BTN_ROLES] + buttons[idx:]


def main_menu_keyboard(is_ceo: bool = False, can_roles: bool = None) -> ReplyKeyboardMarkup:
    """The one-and-only main menu. MENU_VERSION is embedded in placeholder."""
    if can_roles is None:
        can_roles = is_ceo
    rows = [
        # 1) الصندوق والعمليات
        [KeyboardButton(text=BTN_CASHBOX), KeyboardButton(text=BTN_EXPENSE)],
        [KeyboardButton(text=BTN_DEPOSIT), KeyboardButton(text=BTN_WITHDRAW)],
        [KeyboardButton(text=BTN_HISTORY)],
        # 2) الحسابات والالتزامات
        [KeyboardButton(text=BTN_MEMBERS), KeyboardButton(text=BTN_CONTRIB)],
        [KeyboardButton(text=BTN_DEBTS)],
        # 3) التقارير
        [KeyboardButton(text=BTN_REPORT), KeyboardButton(text=BTN_MONTHLY)],
        [KeyboardButton(text=BTN_WEEKLY), KeyboardButton(text=BTN_EXPORT)],
        # 4) إدارة الشركة
        [KeyboardButton(text=BTN_MY_PROFILE), KeyboardButton(text=BTN_SETTINGS)],
    ]
    if can_roles:
        rows.append([KeyboardButton(text=BTN_ROLES)])
    # 5) المساعدة
    rows.append([KeyboardButton(text=BTN_GUIDE)])
    rows.append([KeyboardButton(text=BTN_MAIN)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=f"القائمة {MENU_VERSION} — أو اكتب: يا محاسب",
    )
