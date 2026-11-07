"""First-contact group onboarding. Job title is display-only (not official role)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from rawafed_bot.core.config import settings
from rawafed_bot.database.models.audit_log import AuditLog
from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.onboarding_invite import OnboardingInvite
from rawafed_bot.services.registration_service import RegistrationError, RegistrationService

# Display titles only — never map to elevated permissions automatically.
JOB_TITLE_PRESETS: List[Tuple[str, str]] = [
    ("ceo_title", "الرئيس التنفيذي CEO"),
    ("finance", "مدير مالي"),
    ("accountant", "محاسب"),
    ("ops", "مدير عمليات"),
    ("board", "عضو مجلس إدارة"),
    ("staff", "موظف"),
    ("other", "منصب آخر"),
]

JOB_TITLE_BY_CODE = {code: label for code, label in JOB_TITLE_PRESETS}


class OnboardingService:
    @staticmethod
    def is_registered(db: Session, telegram_id: int) -> bool:
        m = db.query(Member).filter_by(telegram_id=telegram_id, is_active=True).first()
        return m is not None

    @staticmethod
    def get_invite(db: Session, telegram_id: int) -> Optional[OnboardingInvite]:
        return db.query(OnboardingInvite).filter_by(telegram_id=telegram_id).first()

    @staticmethod
    def should_invite(db: Session, telegram_id: int) -> Tuple[bool, str]:
        """Return (should_send_invite, reason_code)."""
        if telegram_id == settings.CEO_TELEGRAM_ID:
            return False, "ceo"
        if OnboardingService.is_registered(db, telegram_id):
            return False, "already_registered"
        invite = OnboardingService.get_invite(db, telegram_id)
        if invite and not invite.responded:
            return False, "already_invited"
        if invite and invite.responded:
            return False, "already_responded"
        remaining = RegistrationService.remaining_slots(db)
        if remaining <= 0:
            return False, "full"
        return True, "ok"

    @staticmethod
    def mark_invited(db: Session, telegram_id: int, chat_id: int = None) -> OnboardingInvite:
        invite = OnboardingService.get_invite(db, telegram_id)
        if invite:
            return invite
        invite = OnboardingInvite(
            telegram_id=telegram_id,
            chat_id=chat_id,
            invited_at=datetime.utcnow(),
            responded=False,
        )
        db.add(invite)
        db.flush()
        actor = (
            db.query(Member).filter_by(is_ceo=True, is_active=True).first()
            or db.query(Member).filter_by(is_active=True).first()
        )
        if actor:
            db.add(AuditLog(
                action="onboard_invite",
                entity_type="onboarding_invite",
                entity_id=invite.id,
                member_id=actor.id,
                new_values=f"telegram_id={telegram_id}, chat_id={chat_id}",
            ))
        db.commit()
        db.refresh(invite)
        return invite

    @staticmethod
    def apply_job_title_choice(
        db: Session,
        telegram_id: int,
        title_code: str,
        custom_title: str = None,
        telegram_username: str = None,
        telegram_full_name: str = None,
        group_id: int = None,
    ) -> Member:
        """Register member with display job_title only. Official role stays board_member."""
        if title_code == "other":
            title = (custom_title or "").strip()
            if not title or len(title) > 100:
                raise RegistrationError("المسمى المخصص غير صالح.")
        else:
            title = JOB_TITLE_BY_CODE.get(title_code)
            if not title:
                raise RegistrationError("خيار المنصب غير معروف.")

        # Display titles that look like CEO do NOT grant CEO powers
        member = RegistrationService.register_self(
            db,
            telegram_id=telegram_id,
            telegram_username=telegram_username,
            telegram_full_name=telegram_full_name,
            group_id=group_id,
        )
        member.job_title = title
        if telegram_full_name and not member.display_name:
            member.display_name = telegram_full_name
        # Ensure never auto-CEO from title choice
        if telegram_id != settings.CEO_TELEGRAM_ID:
            member.is_ceo = False
        db.add(member)

        invite = OnboardingService.get_invite(db, telegram_id)
        if invite:
            invite.responded = True
            invite.chosen_title = title
            invite.completed_at = datetime.utcnow()
            db.add(invite)

        db.add(AuditLog(
            action="onboard_title",
            entity_type="member",
            entity_id=member.id,
            member_id=member.id,
            new_values=f"job_title={title}, display_only=1, code={title_code}",
        ))
        db.commit()
        db.refresh(member)
        return member

    @staticmethod
    def notify_ceo_text(member_name: str, job_title: str, remaining: int) -> str:
        return (
            "🔔 طلب/تسجيل عضو جديد\n"
            f"الاسم: {member_name}\n"
            f"المسمى التعريفي: {job_title}\n"
            f"المقاعد المتبقية: {remaining}\n"
            "ملاحظة: المسمى تعريفي فقط. عيّن المنصب الرسمي من «إدارة المناصب»."
        )
