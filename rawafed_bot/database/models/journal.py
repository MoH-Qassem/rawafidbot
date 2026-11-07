from datetime import datetime
from sqlalchemy import Column, Integer, String, BigInteger, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from rawafed_bot.database.connection import Base


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    entry_number = Column(String(50), unique=True, nullable=False, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True, index=True)
    reference_type = Column(String(50), nullable=True)  # transaction, adjustment, reversal
    reference_id = Column(Integer, nullable=True)
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False, index=True)
    description = Column(Text, nullable=True)
    entry_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(Integer, ForeignKey("members.id"), nullable=False)
    idempotency_key = Column(String(32), unique=True, nullable=True, index=True)

    lines = relationship("JournalLine", back_populates="entry", cascade="all, delete-orphan")


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id = Column(Integer, primary_key=True, index=True)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    debit = Column(BigInteger, default=0, nullable=False)
    credit = Column(BigInteger, default=0, nullable=False)
    description = Column(Text, nullable=True)

    entry = relationship("JournalEntry", back_populates="lines")
    account = relationship("Account")
