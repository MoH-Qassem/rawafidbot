"""Member profile updates."""
from sqlalchemy.orm import Session

from rawafed_bot.database.models.member import Member
from rawafed_bot.database.models.audit_log import AuditLog
from rawafed_bot.services.operation_service import OperationError
from rawafed_bot.services.permission_service import PermissionService


class MemberService:
    @staticmethod
    def profile_card(db: Session, member: Member) -> str:
        role = PermissionService.get_member_role(db, member.id)
        perms = sorted(PermissionService.member_permission_codes(db, member))
        when = member.created_at.strftime("%Y-%m-%d %H:%M") if member.created_at else "—"
        lines = [
            "👤 ملف العضو",
            "────────────",
            f"الاسم الظاهر: {member.display_name or '—'}",
            f"المسمى التعريفي: {member.job_title or '—'}",
            f"Telegram ID: {member.telegram_id}",
            f"Username: @{member.telegram_username}" if member.telegram_username else "Username: —",
            f"تاريخ التسجيل: {when}",
            f"الحالة: {'نشط' if member.is_active else 'ملغى'}",
            f"علم CEO: {'نعم' if member.is_ceo else 'لا'}",
            f"المنصب الرسمي: {role.name_ar if role else '—'}",
            f"عدد الصلاحيات الفعلية: {len(perms)}",
            "",
            "ملاحظة: تعديل المسمى التعريفي لا يغيّر المنصب الرسمي أو الصلاحيات.",
        ]
        return "\n".join(lines)


    @staticmethod
    def update_profile(
        db: Session,
        member_id: int,
        display_name: str = None,
        job_title: str = None,
    ) -> Member:
        try:
            member = db.query(Member).filter_by(id=member_id).first()
            if not member:
                raise OperationError("العضو غير موجود.")
            old = f"display_name={member.display_name}, job_title={member.job_title}"
            if display_name is not None:
                name = display_name.strip()
                if not name or len(name) > 100:
                    raise OperationError("الاسم الظاهر غير صالح.")
                member.display_name = name
            if job_title is not None:
                title = job_title.strip()
                if len(title) > 100:
                    raise OperationError("المسمى الوظيفي طويل جداً.")
                member.job_title = title or None
            db.add(member)
            db.add(AuditLog(
                action="update",
                entity_type="member",
                entity_id=member.id,
                member_id=member.id,
                old_values=old,
                new_values=f"display_name={member.display_name}, job_title={member.job_title}",
            ))
            db.commit()
            db.refresh(member)
            return member
        except Exception:
            db.rollback()
            raise
