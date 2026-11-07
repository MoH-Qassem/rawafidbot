"""Track first-contact onboarding invites so we do not spam the same user."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String

from rawafed_bot.database.connection import Base


class OnboardingInvite(Base):
    __tablename__ = "onboarding_invites"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=True, index=True)
    invited_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    responded = Column(Boolean, default=False, nullable=False)
    chosen_title = Column(String(100), nullable=True)
    completed_at = Column(DateTime, nullable=True)
