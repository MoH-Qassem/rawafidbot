"""Database seeder for initial setup."""
from sqlalchemy.orm import Session

from rawafed_bot.core.config import settings
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.currency import Currency
from rawafed_bot.database.models.account import Account
from rawafed_bot.database.models.expense_category import ExpenseCategory
from rawafed_bot.database.models.bot_setting import BotSetting


def seed_currencies(db: Session):
    currencies = [
        Currency(code="USD", name_ar="دولار أمريكي", name_en="US Dollar", symbol="$", aliases="دولار,دولار أمريكي,USD,$", decimal_places=2),
        Currency(code="SYP", name_ar="ليرة سورية", name_en="Syrian Pound", symbol="ل.س", aliases="ليرة سورية,سوري,SYP,ل.س", decimal_places=2),
        Currency(code="TRY", name_ar="ليرة تركية", name_en="Turkish Lira", symbol="₺", aliases="ليرة تركية,تركي,TRY,₺", decimal_places=2),
    ]
    existing = {c.code for c in db.query(Currency).all()}
    for c in currencies:
        if c.code not in existing:
            db.add(c)
    db.commit()


def seed_members(db: Session):
    """Ensure CEO exists (idempotent). Optional env bootstrap for remaining slots only.

    Never recreates existing telegram IDs. Never deletes members or financial rows.
    If the DB is full of MEMBER_TELEGRAM_IDS placeholders and the real CEO is missing
    with an empty ledger, soft-deactivate those placeholders then ensure CEO.
    """
    from rawafed_bot.services.registration_service import (
        RegistrationError,
        RegistrationService,
    )
    from rawafed_bot.services.permission_service import PermissionService

    if settings.CEO_TELEGRAM_ID:
        try:
            RegistrationService.ensure_ceo_member(db)
        except RegistrationError:
            remediated = RegistrationService.try_remediate_env_placeholder_conflict(db)
            if not remediated:
                raise
            RegistrationService.ensure_ceo_member(db)

    # Optional bootstrap of remaining env IDs — tests only (ALLOW_ENV_MEMBER_BOOTSTRAP=1).
    # Production FadeHost must NOT set this; never deletes or replaces existing rows.
    if settings.ALLOW_ENV_MEMBER_BOOTSTRAP and settings.MEMBER_TELEGRAM_IDS:
        existing = {m.telegram_id for m in db.query(Member).all()}
        active_count = db.query(Member).filter_by(is_active=True).count()
        created = False
        for tid in settings.MEMBER_TELEGRAM_IDS:
            if tid == settings.CEO_TELEGRAM_ID:
                continue
            if tid in existing:
                continue
            if active_count >= settings.MAX_MEMBERS:
                break
            db.add(Member(
                telegram_id=tid,
                is_ceo=False,
                is_active=True,
                profile_completed=False,
            ))
            active_count += 1
            created = True
        if created:
            db.commit()

    PermissionService.seed_catalog(db)
    from rawafed_bot.database.models.role import MemberRole, Role
    board = db.query(Role).filter_by(code="board_member").first()
    if board:
        for m in db.query(Member).filter_by(is_active=True, is_ceo=False).all():
            if not db.query(MemberRole).filter_by(member_id=m.id).first():
                db.add(MemberRole(member_id=m.id, role_id=board.id))
        db.commit()



def seed_accounts(db: Session):
    currencies = db.query(Currency).all()
    members = db.query(Member).all()

    existing = {(a.account_type, a.currency_id, a.member_id) for a in db.query(Account).all()}

    for currency in currencies:
        # Cash box per currency
        key = ("cash_box", currency.id, None)
        if key not in existing:
            db.add(Account(
                account_type="cash_box",
                name=f"صندوق {currency.name_ar}",
                currency_id=currency.id,
                balance=0,
            ))
        # Expense summary per currency
        key = ("expense_summary", currency.id, None)
        if key not in existing:
            db.add(Account(
                account_type="expense_summary",
                name=f"مصروفات {currency.name_ar}",
                currency_id=currency.id,
                balance=0,
            ))
        # Revenue per currency
        key = ("revenue", currency.id, None)
        if key not in existing:
            db.add(Account(
                account_type="revenue",
                name=f"إيرادات {currency.name_ar}",
                currency_id=currency.id,
                balance=0,
            ))
        # Member accounts per currency
        for member in members:
            key = ("member_equity", currency.id, member.id)
            if key not in existing:
                db.add(Account(
                    account_type="member_equity",
                    name=f"حساب {member.telegram_id} - {currency.name_ar}",
                    member_id=member.id,
                    currency_id=currency.id,
                    balance=0,
                ))
            key = ("member_due", currency.id, member.id)
            if key not in existing:
                db.add(Account(
                    account_type="member_due",
                    name=f"مستحقات {member.telegram_id} - {currency.name_ar}",
                    member_id=member.id,
                    currency_id=currency.id,
                    balance=0,
                ))
            key = ("advance_pending", currency.id, member.id)
            if key not in existing:
                db.add(Account(
                    account_type="advance_pending",
                    name=f"عهدة {member.telegram_id} - {currency.name_ar}",
                    member_id=member.id,
                    currency_id=currency.id,
                    balance=0,
                ))
    db.commit()


def seed_expense_categories(db: Session):
    defaults = [
        "مواصلات",
        "ضيافة",
        "مكتب",
        "أدوات",
        "صيانة",
        "اشتراكات",
        "رواتب",
        "أخرى",
    ]
    existing = {c.name for c in db.query(ExpenseCategory).all()}
    for name in defaults:
        if name not in existing:
            db.add(ExpenseCategory(name=name, is_system=(name != "أخرى")))
    db.commit()


def seed_settings(db: Session):
    defaults = [
        ("timezone", settings.TIMEZONE, "المنطقة الزمنية الافتراضية"),
        ("weekly_report_day", str(settings.WEEKLY_REPORT_DAY), "يوم التقرير الأسبوعي (0=أحد … 5=جمعة)"),
        ("weekly_report_hour", str(settings.WEEKLY_REPORT_HOUR), "ساعة إرسال التقرير الأسبوعي"),
        ("monthly_report_day", str(settings.MONTHLY_REPORT_DAY), "يوم إرسال التقرير الشهري"),
        ("monthly_report_hour", str(settings.MONTHLY_REPORT_HOUR), "ساعة إرسال التقرير الشهري"),
    ]
    existing = {s.key for s in db.query(BotSetting).all()}
    for key, value, desc in defaults:
        if key not in existing:
            db.add(BotSetting(key=key, value=value, description=desc))
    db.commit()


def seed_all(db: Session):
    seed_currencies(db)
    seed_members(db)
    seed_accounts(db)
    seed_expense_categories(db)
    seed_settings(db)
    from rawafed_bot.services.permission_service import PermissionService
    PermissionService.seed_catalog(db)
