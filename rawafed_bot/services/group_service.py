"""Company Telegram group setup and notifications."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from rawafed_bot.core.config import settings
from rawafed_bot.database.models.audit_log import AuditLog
from rawafed_bot.database.models.company_group import CompanyGroup
from rawafed_bot.database.models.member import Member
from rawafed_bot.services.registration_service import RegistrationService


WELCOME_TEXT = (
    "مرحباً بكم في مجموعة شركة روافد.\n\n"
    "أنا <b>RAWAFED BOT</b>، المساعد المالي الرسمي للشركة.\n\n"
    "سأتولى تسجيل وتنظيم العمليات المالية، ومتابعة الصندوق والإيداعات "
    "والمصروفات والمستحقات والمساهمات.\n\n"
    "العملات المعتمدة مستقلة تماماً:\n"
    "• الدولار الأمريكي (USD)\n"
    "• الليرة السورية (SYP)\n"
    "• الليرة التركية (TRY)\n\n"
    "يمكنكم استخدام الأزرار المخصصة لتسجيل العمليات والاستعلام عن الحسابات والتقارير.\n"
    "جميع العمليات تخضع للتسجيل والتدقيق، ويمكن تتبع العضو الذي نفّذ كل عملية.\n\n"
    "يسعدني العمل معكم لتنظيم الحسابات المالية لشركة روافد."
)

USAGE_HINT = (
    "📌 <b>طريقة الاستخدام</b>\n"
    "1) اضغط «تسجيل عضويتي» أو أرسل /start مرة واحدة فقط.\n"
    "2) أكمل الاسم الظاهر والمسمى واللقب <b>داخل المجموعة</b>.\n"
    "3) نفّذ العمليات من أزرار القائمة أو بكتابة: يا محاسب، …\n"
    "4) بعد النجاح يُرسل إشعار للمجموعة حسب إعداد الإشعارات.\n"
    "5) غير المسجّلين لا يستطيعون تنفيذ عمليات مالية.\n"
    "6) الخاص اختياري فقط — لا حاجة للانتقال إليه للتدفقات العادية."
)


class GroupError(Exception):
    pass


class GroupService:
    @staticmethod
    def get_by_chat_id(db: Session, chat_id: int) -> Optional[CompanyGroup]:
        return db.query(CompanyGroup).filter_by(chat_id=chat_id).first()

    @staticmethod
    def get_primary(db: Session) -> Optional[CompanyGroup]:
        return (
            db.query(CompanyGroup)
            .filter_by(is_setup_complete=True)
            .order_by(CompanyGroup.id.asc())
            .first()
        )

    @staticmethod
    def setup_group(
        db: Session,
        chat_id: int,
        title: str,
        ceo_telegram_id: int,
        telegram_username: str = None,
        telegram_full_name: str = None,
    ) -> tuple[CompanyGroup, bool]:
        """Return (group, welcome_should_send)."""
        if ceo_telegram_id != settings.CEO_TELEGRAM_ID:
            raise GroupError("⛔ تهيئة المجموعة متاحة للـ CEO فقط.")

        ceo = RegistrationService.ensure_ceo_member(
            db, telegram_username, telegram_full_name
        )
        group = GroupService.get_by_chat_id(db, chat_id)
        if group and group.welcome_sent:
            return group, False

        if not group:
            group = CompanyGroup(
                chat_id=chat_id,
                title=title,
                is_setup_complete=True,
                welcome_sent=False,
                setup_by_member_id=ceo.id,
                notify_operations=True,
                prefer_private_flows=False,
                notify_detail_level="detailed",
            )
            db.add(group)
            db.flush()
        else:
            group.title = title or group.title
            group.is_setup_complete = True
            group.setup_by_member_id = ceo.id
            db.add(group)

        send_welcome = not group.welcome_sent
        if send_welcome:
            group.welcome_sent = True
            db.add(group)

        db.add(AuditLog(
            action="setup",
            entity_type="company_group",
            entity_id=group.id,
            member_id=ceo.id,
            new_values=f"chat_id={chat_id}, title={title}",
        ))
        db.commit()
        db.refresh(group)
        return group, send_welcome

    @staticmethod
    def mark_bot_removed(db: Session, chat_id: int) -> None:
        group = GroupService.get_by_chat_id(db, chat_id)
        if not group:
            return
        group.notes = ((group.notes or "") + "\nbot_removed").strip()
        db.add(group)
        db.commit()

    @staticmethod
    def format_operation_notice(
        *,
        tx_id: int,
        member_name: str,
        amount_text: str,
        op_type: str,
        description: str,
        when: str,
        balance_text: str,
    ) -> str:
        return (
            f"✅ عملية مالية جديدة\n"
            f"#{tx_id} | {op_type}\n"
            f"المبلغ: {amount_text}\n"
            f"بواسطة: {member_name}\n"
            f"{description}\n"
            f"{when}\n"
            f"رصيد الصندوق بعد العملية: {balance_text}"
        )
