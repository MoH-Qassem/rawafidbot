from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey
from sqlalchemy.orm import relationship
from rawafed_bot.database.connection import Base


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_type = Column(String(50), nullable=False, index=True)
    # Types: cash_box, member_equity, member_due, advance_pending, expense, revenue
    name = Column(String(100), nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=True, index=True)
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False, index=True)
    balance = Column(BigInteger, default=0, nullable=False)  # smallest units

    member = relationship("Member")
    currency = relationship("Currency")
