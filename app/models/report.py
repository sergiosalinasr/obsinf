"""Reportes completos conservados junto con sus datos de entrada."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Report(Base):
    """Documento histórico generado sin modificar resultados originales."""

    __tablename__ = "reports"

    __table_args__ = (
        UniqueConstraint("company_id", "id"),
        UniqueConstraint(
            "company_id",
            "request_sha256",
            name="uq_reports_company_request",
        ),
        CheckConstraint(
            "period_start < period_end",
            name="period_order",
        ),
        CheckConstraint(
            "jsonb_typeof(selection_snapshot) = 'object'",
            name="selection_object",
        ),
        CheckConstraint(
            "length(btrim(content_markdown)) > 0 "
            "AND length(btrim(generator_version)) > 0 "
            "AND length(btrim(timezone)) > 0",
            name="required_text",
        ),
        CheckConstraint(
            "length(request_sha256) = 64",
            name="request_hash_length",
        ),
        Index("ix_reports_company_created", "company_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id")
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(Text)

    selection_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_markdown: Mapped[str] = mapped_column(Text)
    generator_version: Mapped[str] = mapped_column(Text)
    request_sha256: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
    )