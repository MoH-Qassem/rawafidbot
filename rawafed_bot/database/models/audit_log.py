from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from rawafed_bot.database.connection import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String(50), nullable=False, index=True)  # create, update, delete, reverse
    entity_type = Column(String(50), nullable=False, index=True)  # transaction, journal_entry, member, ...
    entity_id = Column(Integer, nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    old_values = Column(Text, nullable=True)
    new_values = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
