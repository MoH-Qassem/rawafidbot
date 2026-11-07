from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, DateTime, ForeignKey, String, Text
from rawafed_bot.database.connection import Base


class Advance(Base):
    __tablename__ = "advances"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False, index=True)
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False, index=True)
    amount = Column(BigInteger, nullable=False)
    purpose = Column(Text, nullable=True)
    status = Column(String(20), default="open", nullable=False)  # open, partially_settled, fully_settled
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(Integer, ForeignKey("members.id"), nullable=False)


class AdvanceSettlement(Base):
    __tablename__ = "advance_settlements"

    id = Column(Integer, primary_key=True, index=True)
    advance_id = Column(Integer, ForeignKey("advances.id"), nullable=False, index=True)
    expense_amount = Column(BigInteger, default=0, nullable=False)
    returned_amount = Column(BigInteger, default=0, nullable=False)
    additional_amount = Column(BigInteger, default=0, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(Integer, ForeignKey("members.id"), nullable=False)
