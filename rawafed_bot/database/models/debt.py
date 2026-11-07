from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, DateTime, ForeignKey, String, Text
from rawafed_bot.database.connection import Base


class MemberDebt(Base):
    __tablename__ = "member_debts"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False, index=True)
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False, index=True)
    amount = Column(BigInteger, nullable=False)  # amount company owes to member
    remaining = Column(BigInteger, nullable=False)
    description = Column(Text, nullable=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    status = Column(String(20), default="active", nullable=False)  # active, repaid
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
