from sqlalchemy import Column, Integer, String, Text
from rawafed_bot.database.connection import Base


class BotSetting(Base):
    __tablename__ = "bot_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
