from sqlalchemy import Column, Integer, String, Boolean
from rawafed_bot.database.connection import Base


class Currency(Base):
    __tablename__ = "currencies"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(10), unique=True, nullable=False)  # USD, SYP, TRY
    name_ar = Column(String(50), nullable=False)
    name_en = Column(String(50), nullable=False)
    symbol = Column(String(10), nullable=False)
    aliases = Column(String(200), nullable=True)  # comma-separated aliases
    is_active = Column(Boolean, default=True, nullable=False)
    decimal_places = Column(Integer, default=2, nullable=False)
