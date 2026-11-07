from datetime import datetime
from sqlalchemy import Column, Integer, String, BigInteger, DateTime, ForeignKey, Text, Enum as SQLAEnum
import enum
from rawafed_bot.database.connection import Base


class ContributionStatus(str, enum.Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    COMPLETED = "completed"
    OVERDUE = "overdue"


class ContributionRequest(Base):
    __tablename__ = "contribution_requests"

    id = Column(Integer, primary_key=True, index=True)
    amount = Column(BigInteger, nullable=False)
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(DateTime, nullable=True)
    status = Column(String(20), default="pending", nullable=False)
    created_by = Column(Integer, ForeignKey("members.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ContributionObligation(Base):
    __tablename__ = "contribution_obligations"

    id = Column(Integer, primary_key=True, index=True)
    contribution_request_id = Column(Integer, ForeignKey("contribution_requests.id"), nullable=False, index=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False, index=True)
    amount = Column(BigInteger, nullable=False)
    paid_amount = Column(BigInteger, default=0, nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
