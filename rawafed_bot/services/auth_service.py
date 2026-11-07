"""Authentication & Authorization Service for Rawafed Bot.

Identity is always Telegram User ID. Permissions are checked in services.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from rawafed_bot.core.config import settings
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.permission_service import PermissionService
from rawafed_bot.services.permissions_catalog import CREATE_CONTRIBUTION


class AuthService:
    @staticmethod
    def is_ceo(telegram_id: int) -> bool:
        return telegram_id == settings.CEO_TELEGRAM_ID

    @staticmethod
    def is_known_user(db: Session, telegram_id: int) -> bool:
        if AuthService.is_ceo(telegram_id):
            return True
        # Legacy env allow-list (tests / optional bootstrap)
        if telegram_id in settings.MEMBER_TELEGRAM_IDS:
            return True
        member = db.query(Member).filter_by(telegram_id=telegram_id, is_active=True).first()
        return member is not None

    @staticmethod
    def get_member_by_telegram_id(db: Session, telegram_id: int) -> Optional[Member]:
        return db.query(Member).filter(Member.telegram_id == telegram_id).first()

    @staticmethod
    def get_or_create_member(db: Session, telegram_id: int) -> Member:
        """Create member only for CEO or legacy env IDs — interactive registration otherwise."""
        member = AuthService.get_member_by_telegram_id(db, telegram_id)
        if member:
            desired_ceo = AuthService.is_ceo(telegram_id)
            if member.is_ceo != desired_ceo:
                member.is_ceo = desired_ceo
                db.add(member)
                db.commit()
                db.refresh(member)
            return member

        if AuthService.is_ceo(telegram_id):
            from rawafed_bot.services.registration_service import RegistrationService
            return RegistrationService.ensure_ceo_member(db)

        if telegram_id not in settings.MEMBER_TELEGRAM_IDS:
            raise PermissionError("⚠️ أنت غير مصرح لك باستخدام هذا البوت.")

        from rawafed_bot.core.config import settings as cfg
        if db.query(Member).filter_by(is_active=True).count() >= cfg.MAX_MEMBERS:
            raise PermissionError("اكتمل عدد الأعضاء.")

        member = Member(
            telegram_id=telegram_id,
            is_ceo=False,
            is_active=True,
            profile_completed=False,
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        from rawafed_bot.database.seeder import seed_accounts
        from rawafed_bot.services.permission_service import PermissionService as PS
        from rawafed_bot.database.models.role import MemberRole, Role
        PS.seed_catalog(db)
        role = db.query(Role).filter_by(code="board_member").first()
        if role:
            db.add(MemberRole(member_id=member.id, role_id=role.id))
            db.commit()
        seed_accounts(db)
        return member

    @staticmethod
    def require_member(db: Session, telegram_id: int) -> Member:
        if AuthService.is_ceo(telegram_id):
            from rawafed_bot.services.registration_service import RegistrationService
            member = RegistrationService.ensure_ceo_member(db)
            if not member.is_active:
                raise PermissionError("⚠️ حسابك غير نشط.")
            return member

        member = AuthService.get_member_by_telegram_id(db, telegram_id)
        if member and member.is_active:
            return member

        # Legacy bootstrap from env list
        if telegram_id in settings.MEMBER_TELEGRAM_IDS:
            return AuthService.get_or_create_member(db, telegram_id)

        raise PermissionError(
            "⚠️ أنت غير مسجّل في نظام روافد.\n"
            "اطلب من الـ CEO تهيئة المجموعة ثم اضغط «تسجيل عضويتي»."
        )

    @staticmethod
    def require_ceo(db: Session, telegram_id: int) -> Member:
        member = AuthService.require_member(db, telegram_id)
        if not member.is_ceo and telegram_id != settings.CEO_TELEGRAM_ID:
            raise PermissionError("⛔ هذه العملية متاحة للـ CEO فقط.")
        return member

    @staticmethod
    def require_permission(db: Session, telegram_id: int, permission_code: str) -> Member:
        member = AuthService.require_member(db, telegram_id)
        PermissionService.require(db, member, permission_code)
        return member

    @staticmethod
    def require_contribution_creator(db: Session, telegram_id: int) -> Member:
        return AuthService.require_permission(db, telegram_id, CREATE_CONTRIBUTION)

    @staticmethod
    def get_all_members(db: Session) -> List[Member]:
        return db.query(Member).filter(Member.is_active == True).order_by(Member.id).all()
