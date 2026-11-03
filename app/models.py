# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""ORM models. Tenant data is scoped by user_id; JobListing is a shared catalog."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    applications: Mapped[list["Application"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    preference: Mapped[Optional["UserPreference"]] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")


class JobListing(Base):
    __tablename__ = "job_listings"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_job_source_ext"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(256))
    title: Mapped[str] = mapped_column(String(512))
    company: Mapped[str] = mapped_column(String(256), default="")
    location: Mapped[str] = mapped_column(String(256), default="")
    url: Mapped[str] = mapped_column(String(1024), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    sector: Mapped[str] = mapped_column(String(128), default="")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=True)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_app_user_job"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_listings.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="saved")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="applications")
    job: Mapped[JobListing] = relationship()


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    field: Mapped[str] = mapped_column(String(128), default="")
    keywords: Mapped[str] = mapped_column(Text, default="")
    remote_only: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="preference")

    def keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.keywords.split(",") if k.strip()]


class UserProfile(Base):
    """What a person brings and what they want their work to change. Private to its user."""
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    skills: Mapped[str] = mapped_column(Text, default="")
    experience: Mapped[str] = mapped_column(Text, default="")
    values: Mapped[str] = mapped_column(Text, default="")
    causes: Mapped[str] = mapped_column(Text, default="")
    desired_impact: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(256), default="")
    remote_preference: Mapped[str] = mapped_column(String(16), default="any")  # remote | hybrid | onsite | any
    comp_floor: Mapped[int] = mapped_column(Integer, default=0)  # yearly, in the posting's currency
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JobFeedback(Base):
    """Save / dismiss signals that tune one user's ranking."""
    __tablename__ = "job_feedback"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_feedback_user_job"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_listings.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(16))  # save | dismiss
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScanState(Base):
    """Small key/value store for scanner bookkeeping (e.g. the board rotation cursor)."""
    __tablename__ = "scan_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
