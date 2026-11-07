from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean, ForeignKey
from rawafed_bot.database.connection import Base


class Member(Base):
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    telegram_username = Column(String(100), nullable=True)
    telegram_full_name = Column(String(200), nullable=True)
    display_name = Column(String(100), nullable=True)
    job_title = Column(String(100), nullable=True)
    is_ceo = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    profile_completed = Column(Boolean, default=False, nullable=False)
    # Plain int to avoid circular FK with company_groups
    registered_via_group_id = Column(Integer, nullable=True, index=True)
    deactivated_at = Column(DateTime, nullable=True)
    deactivated_by = Column(Integer, ForeignKey("members.id"), nullable=True)
    deactivation_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def get_display_name(self) -> str:
        """Visible name only — job_title is shown separately (avoids «اسم (لقب) (منصب)»)."""
        return self.display_name or self.telegram_full_name or f"عضو {self.telegram_id}"

    def get_label_with_title(self) -> str:
        name = self.get_display_name()
        title = (self.job_title or "").strip()
        if not title:
            return name
        # Don't double-wrap if title already embedded
        if title in name:
            return name
        return f"{name} — {title}"
