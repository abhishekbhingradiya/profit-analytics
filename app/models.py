from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    organization: Mapped[Organization] = relationship()


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("org_id", "external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    segment: Mapped[str] = mapped_column(String(60))
    region: Mapped[str] = mapped_column(String(60))
    industry: Mapped[str] = mapped_column(String(60), default="Unknown")
    channel: Mapped[str] = mapped_column(String(60), default="Unknown")
    signup_month: Mapped[date | None] = mapped_column(Date, nullable=True)


class RevenueEntry(Base):
    """Monthly recurring revenue per customer (one row per customer-month)."""

    __tablename__ = "revenue_monthly"
    __table_args__ = (Index("ix_revenue_org_month", "org_id", "month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    month: Mapped[date] = mapped_column(Date)
    plan: Mapped[str] = mapped_column(String(60), default="Default")
    list_mrr: Mapped[float] = mapped_column(Float)
    mrr: Mapped[float] = mapped_column(Float)


class CostEntry(Base):
    """Monthly cost by category; customer_id is set for directly attributable costs."""

    __tablename__ = "costs_monthly"
    __table_args__ = (Index("ix_costs_org_month", "org_id", "month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    month: Mapped[date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(40))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    amount: Mapped[float] = mapped_column(Float)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User | None] = relationship()
