from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Template(Base):
    """
    Pointer to a bot in Cryptorg that is used as a template.
    status=0 in Cryptorg = inactive (template), status=4 = active.
    """
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)           # display name
    cryptorg_bot_id = Column(Integer, nullable=False, unique=True)
    enabled = Column(Boolean, default=True)

    running_bots = relationship("RunningBot", back_populates="template")


class RunningBot(Base):
    __tablename__ = "running_bots"

    id = Column(Integer, primary_key=True)
    telegram_user = Column(Integer, nullable=False)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True)
    cryptorg_bot_id = Column(Integer, nullable=False)
    deal_id = Column(Integer)                        # active deal id
    pair = Column(String, nullable=False)            # e.g. DOGEUSDT
    status = Column(String, default="active")        # active / stopped / closed / error
    created_at = Column(DateTime, default=datetime.utcnow)
    stopped_at = Column(DateTime)

    template = relationship("Template", back_populates="running_bots")
