"""Interactive member self-registration (max members, CEO protected)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from rawafed_bot.core.config import settings
from rawafed_bot.database.models.audit_log import AuditLog
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.role import MemberRole, Role
from rawafed_bot.database.seeder import seed_accounts
from rawafed_bot.services.permission_service import PermissionService


class RegistrationError(Exception):
    pass


class RegistrationService:
    @staticmethod
    def active_count(db: Session) -> int:
        return db.query(Member).filter_by(is_active=True).count()

    @staticmethod
    def remaining_slots(db: Session) -> int:
        return max(0, settings.MAX_MEMBERS - RegistrationService.active_count(db))

    @staticmethod
    def ensure_ceo_member(
        db: Session,
        telegram_username: str = None,
        telegram_full_name: str = None,
    ) -> Member:
        """Idempotent CEO ensure: update if present, create only when a slot exists."""
        ceo_id = settings.CEO_TELEGRAM_ID
        if not ceo_id:
            raise RegistrationError("CEO_TELEGRAM_ID غير مضبوط.")

        member = db.query(Member).filter_by(telegram_id=ceo_id).first()
        if member:
            member.is_ceo = True
            member.is_active = True
            if telegram_username:
                member.telegram_username = telegram_username
            if telegram_full_name:
                member.telegram_full_name = telegram_full_name
                if not member.display_name:
                    member.display_name = telegram_full_name
            db.add(member)
            # Only one CEO flag at a time
            for other in db.query(Member).filter(
                Member.is_ceo == True, Member.id != member.id  # noqa: E712
            ).all():
                other.is_ceo = False
                db.add(other)
            db.commit()
            db.refresh(member)
        else:
            if RegistrationService.active_count(db) >= settings.MAX_MEMBERS:
                raise RegistrationError(
                    "تعذر إنشاء حساب الـ CEO: اكتمل عدد الأعضاء النشطين "
                    f"({settings.MAX_MEMBERS}) دون وجود CEO_TELEGRAM_ID الحالي في قاعدة البيانات. "
                    "لا يمكن تجاوز الحد ولا إلغاء عضوية تلقائياً عند وجود عمليات مالية. "
                    "راجع الأعضاء التمهيديين من MEMBER_TELEGRAM_IDS أو أعد تفعيل مسار التصحيح الآمن."
                )
            member = Member(
                telegram_id=ceo_id,
                telegram_username=telegram_username,
                telegram_full_name=telegram_full_name,
                display_name=telegram_full_name or "CEO",
                is_ceo=True,
                is_active=True,
                profile_completed=bool(telegram_full_name),
            )
            db.add(member)
            db.commit()
            db.refresh(member)
            db.add(AuditLog(
                action="register",
                entity_type="member",
                entity_id=member.id,
                member_id=member.id,
                new_values="ceo=True (ensure_ceo_member)",
            ))
            db.commit()

        PermissionService.seed_catalog(db)
        ceo_role = db.query(Role).filter_by(code="ceo").first()
        if ceo_role:
            link = db.query(MemberRole).filter_by(member_id=member.id).first()
            if not link:
                db.add(MemberRole(
                    member_id=member.id, role_id=ceo_role.id, assigned_by=member.id
                ))
                db.commit()
        seed_accounts(db)
        return member

    @staticmethod
    def try_remediate_env_placeholder_conflict(db: Session) -> bool:
        """Soft-deactivate env-bootstrap placeholders so the real CEO can be added.

        Runs ONLY when ALL of these hold (never deletes rows or ledger data):
        - CEO_TELEGRAM_ID is set and has no member row
        - Active members already fill MAX_MEMBERS
        - Every active member telegram_id is in MEMBER_TELEGRAM_IDS
        - Database has zero transactions and zero journal entries
        """
        from sqlalchemy import text

        ceo_id = settings.CEO_TELEGRAM_ID
        if not ceo_id:
            return False
        if db.query(Member).filter_by(telegram_id=ceo_id).first():
            return False

        env_ids = set(settings.MEMBER_TELEGRAM_IDS)
        if not env_ids:
            return False

        active = db.query(Member).filter_by(is_active=True).all()
        if len(active) < settings.MAX_MEMBERS:
            return False
        if any(m.telegram_id not in env_ids for m in active):
            return False

        # Raw counts avoid ORM failures on partially-patched legacy schemas
        tx_count = db.execute(text("SELECT COUNT(*) FROM transactions")).scalar() or 0
        je_count = db.execute(text("SELECT COUNT(*) FROM journal_entries")).scalar() or 0
        if tx_count > 0 or je_count > 0:
            return False

        for m in active:
            m.is_active = False
            m.is_ceo = False
            m.deactivated_at = datetime.utcnow()
            m.deactivation_reason = (
                "تصحيح تمهيدي آمن: معرفات MEMBER_TELEGRAM_IDS لا تطابق "
                "CEO_TELEGRAM_ID (دفتر القيود فارغ بالكامل)"
            )[:255]
            db.add(m)
            db.add(AuditLog(
                action="unregister",
                entity_type="member",
                entity_id=m.id,
                member_id=m.id,
                new_values="soft_deactivate_env_placeholder_for_ceo",
            ))
        db.commit()
        return True

    @staticmethod
    def register_self(
        db: Session,
        telegram_id: int,
        telegram_username: str = None,
        telegram_full_name: str = None,
        group_id: int = None,
    ) -> Member:
        if telegram_id == settings.CEO_TELEGRAM_ID:
            return RegistrationService.ensure_ceo_member(
                db, telegram_username, telegram_full_name
            )

        existing = db.query(Member).filter_by(telegram_id=telegram_id).first()
        if existing:
            if existing.is_active:
                raise RegistrationError("أنت مسجّل مسبقاً.")
            raise RegistrationError(
                "تم إلغاء تسجيلك سابقاً. يرجى التواصل مع الـ CEO لإعادة التفعيل."
            )

        if RegistrationService.active_count(db) >= settings.MAX_MEMBERS:
            raise RegistrationError(
                f"اكتمل عدد أعضاء الشركة ({settings.MAX_MEMBERS}). لا يمكن تسجيل عضو إضافي."
            )

        member = Member(
            telegram_id=telegram_id,
            telegram_username=telegram_username,
            telegram_full_name=telegram_full_name,
            is_ceo=False,
            is_active=True,
            profile_completed=False,
            registered_via_group_id=group_id,
        )
        db.add(member)
        db.commit()
        db.refresh(member)

        PermissionService.seed_catalog(db)
        default_role = db.query(Role).filter_by(code="board_member", is_active=True).first()
        if default_role:
            db.add(MemberRole(member_id=member.id, role_id=default_role.id))
        db.add(AuditLog(
            action="register",
            entity_type="member",
            entity_id=member.id,
            member_id=member.id,
            new_values=f"telegram_id={telegram_id}, username={telegram_username}",
        ))
        db.commit()
        seed_accounts(db)
        db.refresh(member)
        return member

    @staticmethod
    def complete_profile(
        db: Session, member_id: int, display_name: str, job_title: str = None
    ) -> Member:
        member = db.query(Member).filter_by(id=member_id).first()
        if not member or not member.is_active:
            raise RegistrationError("العضو غير موجود.")
        name = (display_name or "").strip()
        if not name or len(name) > 100:
            raise RegistrationError("الاسم الظاهر غير صالح.")
        member.display_name = name
        member.job_title = (job_title or "").strip() or None
        member.profile_completed = True
        db.add(member)
        db.add(AuditLog(
            action="update",
            entity_type="member",
            entity_id=member.id,
            member_id=member.id,
            new_values=f"display_name={name}, job_title={member.job_title}",
        ))
        db.commit()
        db.refresh(member)
        return member

    @staticmethod
    def unregister_member(
        db: Session, target_member_id: int, actor: Member, reason: str = None
    ) -> Member:
        if not actor.is_ceo:
            raise RegistrationError("إلغاء التسجيل متاح للـ CEO فقط.")
        target = db.query(Member).filter_by(id=target_member_id).first()
        if not target:
            raise RegistrationError("العضو غير موجود.")
        if target.is_ceo or target.telegram_id == settings.CEO_TELEGRAM_ID:
            raise RegistrationError("لا يمكن إلغاء تسجيل الـ CEO.")
        if not target.is_active:
            raise RegistrationError("العضو غير نشط مسبقاً.")
        target.is_active = False
        target.deactivated_at = datetime.utcnow()
        target.deactivated_by = actor.id
        target.deactivation_reason = (reason or "إلغاء تسجيل بواسطة CEO")[:255]
        db.add(target)
        db.add(AuditLog(
            action="unregister",
            entity_type="member",
            entity_id=target.id,
            member_id=actor.id,
            new_values=f"deactivated, reason={target.deactivation_reason}",
        ))
        db.commit()
        db.refresh(target)
        return target

    @staticmethod
    def registration_status(db: Session) -> dict:
        active = db.query(Member).filter_by(is_active=True).order_by(Member.id).all()
        return {
            "active": active,
            "count": len(active),
            "max": settings.MAX_MEMBERS,
            "remaining": max(0, settings.MAX_MEMBERS - len(active)),
            "complete": len(active) >= settings.MAX_MEMBERS,
        }
