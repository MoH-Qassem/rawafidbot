from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Enum as SQLAEnum
import enum
from rawafed_bot.database.connection import Base


class ReportFrequency(str, enum.Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ScheduledReport(Base):
    __tablename__ = "scheduled_reports"

    id = Column(Integer, primary_key=True, index=True)
    frequency = Column(String(20), nullable=False)
    report_type = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_sent_at = Column(DateTime, nullable=True)
    next_due_at = Column(DateTime, nullable=True)
    config = Column(Text, nullable=True)
