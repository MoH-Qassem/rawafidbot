"""Telegram company group linkage and setup state."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from rawafed_bot.database.connection import Base


class CompanyGroup(Base):
    __tablename__ = "company_groups"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(BigInteger, unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=True)
    is_setup_complete = Column(Boolean, default=False, nullable=False)
    welcome_sent = Column(Boolean, default=False, nullable=False)
    notify_operations = Column(Boolean, default=True, nullable=False)
    # brief | detailed | off
    notify_detail_level = Column(String(20), default="detailed", nullable=False)
    prefer_private_flows = Column(Boolean, default=False, nullable=False)
    setup_by_member_id = Column(Integer, ForeignKey("members.id"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
