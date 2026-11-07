"""Interactive usage guide — entirely inside the group/chat."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from rawafed_bot.bot.keyboards.main_menu import BTN_GUIDE, BTN_MAIN, main_menu_keyboard, texts_for
from rawafed_bot.database.models.member import Member
from rawafed_bot.utils.callbacks import GUIDE, pack, unpack

router = Router(name="guide")

PAGES = {
    "home": (
        "📖 دليل الاستخدام والمزايا\n"
        "────────────\n"
        "اختر قسماً:",
        [
            ("كيف أستخدم البوت؟", "how"),
            ("تسجيل المصروفات", "expense"),
            ("تسجيل الإيداعات", "deposit"),
            ("تسجيل السحوبات", "withdraw"),
            ("الصندوق والعملات", "cash"),
            ("المساهمات", "contrib"),
            ("الديون والمستحقات", "debts"),
            ("العهد المالية", "adv"),
            ("كشف حساب عضو", "member"),
            ("سجل العمليات", "hist"),
            ("التقارير", "reports"),
            ("المناصب والصلاحيات", "roles"),
            ("الأسئلة الشائعة", "faq"),
        ],
    ),
    "how": (
        "كيف أستخدم البوت؟\n\n"
        "1) اعمل داخل مجموعة الشركة.\n"
        "2) اكتب نداءً مثل: يا محاسب، كم رصيد الصندوق؟\n"
        "3) أو استخدم أزرار القائمة.\n"
        "4) للعمليات المالية يعرض البوت ملخصاً ثم يطلب تأكيدك قبل الحفظ.",
        [],
    ),
    "expense": (
        "تسجيل المصروفات\n\n"
        "اكتب مثلاً:\n"
        "«يا محاسب، سجل 100 دولار مصروف نقل»\n"
        "«مصروف 50 ليرة سورية أوراق»\n\n"
        "سيستخرج المبلغ والعملة والوصف، يسألك عن الناقص، ثم يعرض تأكيداً.",
        [],
    ),
    "deposit": (
        "تسجيل الإيداعات\n\n"
        "«يا محاسب، سجل إيداع 500 دولار»\n"
        "أو من القائمة: ➕ تسجيل إيداع",
        [],
    ),
    "withdraw": (
        "تسجيل السحوبات والعهد\n\n"
        "«يا محاسب، سجل سحب 100 دولار»\n"
        "أو من القائمة: 💳 تسجيل سحب ثم اختر سحب نهائي أو عهدة.",
        [],
    ),
    "cash": (
        "الصندوق والعملات\n\n"
        "العملات مستقلة: USD / SYP / TRY — بلا تحويل بينها.\n"
        "«يا محاسب، كم رصيد الصندوق؟»\n"
        "«يا محاسب، كم معنا بالدولار؟»",
        [],
    ),
    "contrib": (
        "المساهمات\n\n"
        "«يا محاسب، من لم يسدد المساهمة؟»\n"
        "إنشاء الطلبات: صلاحية CEO عادةً من قائمة المساهمات.",
        [],
    ),
    "debts": (
        "الديون والمستحقات\n\n"
        "من القائمة: 📒 الديون والمستحقات\n"
        "أو: «يا محاسب، ما الديون المستحقة؟»",
        [],
    ),
    "adv": (
        "العهد المالية\n\n"
        "سجّل سحباً كعهدة من قائمة السحب، ثم سوِّها لاحقاً بمصروف + معاد للصندوق.",
        [],
    ),
    "member": (
        "كشف حساب عضو\n\n"
        "«يا محاسب، اعرض مصاريف أحمد هذا الشهر»\n"
        "أو: 👥 حسابات الأعضاء",
        [],
    ),
    "hist": (
        "سجل العمليات\n\n"
        "«يا محاسب، اعرض آخر عشر عمليات»\n"
        "أو زر 📋 سجل العمليات",
        [],
    ),
    "reports": (
        "التقارير\n\n"
        "أزرار: 📊 التقرير المالي / 📅 الشهري / 📆 الأسبوعي / 📥 Excel\n"
        "وتقارير مجدولة أسبوعياً وشهرياً.",
        [],
    ),
    "roles": (
        "المناصب والصلاحيات\n\n"
        "المسمى التعريفي ≠ الصلاحيات.\n"
        "المناصب الرسمية الفريدة (مثل محاسب) لشاغل واحد.\n"
        "النقل يتم بطلب وموافقة CEO من 🏢 المناصب والصلاحيات.",
        [],
    ),
    "faq": (
        "أسئلة شائعة\n\n"
        "س: هل أحتاج المحادثة الخاصة؟\n"
        "ج: لا — كل التدفقات العادية داخل المجموعة.\n\n"
        "س: اخترت محاسب ولم أحصل على صلاحيات؟\n"
        "ج: المسمى تعريفي؛ الـ CEO يعيّن المنصب الرسمي.\n\n"
        "س: البوت لا يرى رسائلي؟\n"
        "ج: عطّل Group Privacy من BotFather أو استخدم @mention.",
        [],
    ),
}


def _kb(page: str) -> InlineKeyboardMarkup:
    text, links = PAGES.get(page, PAGES["home"])
    rows = []
    if page == "home":
        for label, key in links:
            rows.append([InlineKeyboardButton(text=label, callback_data=pack(GUIDE, key))])
    else:
        rows.append([InlineKeyboardButton(text="⬅️ رجوع للدليل", callback_data=pack(GUIDE, "home"))])
    rows.append([InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data=pack(GUIDE, "main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text.in_(texts_for(BTN_GUIDE)))
async def open_guide(message: Message, state: FSMContext, member: Member = None):
    await state.clear()
    text, _ = PAGES["home"]
    await message.answer(text, reply_markup=_kb("home"))


@router.message(F.text == BTN_MAIN)
async def main_menu(message: Message, state: FSMContext, member: Member = None):
    await state.clear()
    is_ceo = bool(member and member.is_ceo)
    can_roles = is_ceo
    if member:
        from rawafed_bot.database.connection import get_db_context
        from rawafed_bot.services.permission_service import PermissionService
        from rawafed_bot.services.permissions_catalog import MANAGE_ROLES
        with get_db_context() as db:
            m = db.query(Member).filter_by(id=member.id).first()
            can_roles = bool(m and PermissionService.has_permission(db, m, MANAGE_ROLES))
    from rawafed_bot.core.version import WELCOME_REGISTERED
    await message.answer(
        WELCOME_REGISTERED if member else "القائمة الرئيسية:",
        reply_markup=main_menu_keyboard(is_ceo=is_ceo, can_roles=can_roles),
    )


@router.callback_query(F.data.startswith(f"{GUIDE}:"))
async def guide_nav(callback: CallbackQuery, member: Member = None):
    page = unpack(callback.data)[1]
    if page == "main":
        is_ceo = bool(member and member.is_ceo)
        await callback.message.answer(
            "القائمة الرئيسية:", reply_markup=main_menu_keyboard(is_ceo=is_ceo)
        )
        await callback.answer()
        return
    text, _ = PAGES.get(page, PAGES["home"])
    try:
        await callback.message.edit_text(text, reply_markup=_kb(page))
    except Exception:
        await callback.message.answer(text, reply_markup=_kb(page))
    await callback.answer()
