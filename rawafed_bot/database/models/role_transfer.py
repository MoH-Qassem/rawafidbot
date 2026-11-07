"""Pending unique-role transfer requests awaiting CEO approval."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from rawafed_bot.database.connection import Base


class RoleTransferRequest(Base):
    __tablename__ = "role_transfer_requests"

    id = Column(Integer, primary_key=True, index=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False, index=True)
    requester_id = Column(Integer, ForeignKey("members.id"), nullable=False, index=True)
    current_holder_id = Column(Integer, ForeignKey("members.id"), nullable=True)
    status = Column(String(20), default="pending", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_by = Column(Integer, ForeignKey("members.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
