"""SQLAlchemy models for conversation persistence."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class ConversationSession(Base):
    """A chat thread (maps to frontend session id)."""

    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), unique=True, nullable=False, index=True)
    title = Column(String(256), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class Incident(Base):
    """An incident reported from the map / external system (Phase 6.3 event-driven entry).

    Links to an agent session so the chat thread is traceable from the incident.
    """

    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(String(64), unique=True, nullable=False, index=True)
    session_id = Column(String(64), nullable=False, index=True)
    source = Column(String(32), default="webhook", comment="webhook / manual / map")
    status = Column(String(32), default="active", comment="active / resolved / escalated")
    payload_json = Column(Text, default="{}", comment="Original webhook payload (JSON)")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    hitl_since = Column(DateTime, nullable=True, comment="Timestamp when agent entered HITL (null = not waiting)")
