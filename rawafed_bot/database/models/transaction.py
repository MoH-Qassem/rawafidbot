from datetime import datetime
from sqlalchemy import Column, Integer, String, BigInteger, DateTime, ForeignKey, Text, Enum as SQLAEnum
import enum
from rawafed_bot.database.connection import Base


class TransactionType(str, enum.Enum):
    DEPOSIT = "deposit"
    EXPENSE = "expense"
    WITHDRAWAL = "withdrawal"
    PERSONAL_EXPENSE = "personal_expense"  # expense paid by member from own money
    DEBT_REPAYMENT = "debt_repayment"
    ADVANCE_ISSUED = "advance_issued"
    ADVANCE_SETTLEMENT = "advance_settlement"
    REVERSAL = "reversal"


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_type = Column(String(30), nullable=False, index=True)
    amount = Column(BigInteger, nullable=False)  # smallest units, always positive
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False, index=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("expense_categories.id"), nullable=True)
    description = Column(Text, nullable=True)
    recipient = Column(String(200), nullable=True)  # for withdrawals / advances
    contribution_request_id = Column(Integer, ForeignKey("contribution_requests.id"), nullable=True)
    advance_id = Column(Integer, ForeignKey("advances.id"), nullable=True)
    debt_id = Column(Integer, ForeignKey("member_debts.id"), nullable=True)
    reversed_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    status = Column(String(20), default="active", nullable=False)  # active, cancelled, reversed
    idempotency_key = Column(String(32), unique=True, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(Integer, ForeignKey("members.id"), nullable=False)
