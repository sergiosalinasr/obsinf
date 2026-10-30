"""Correlaciones entre hallazgos de recursos relacionados."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Correlation(Base):
    """Resultado conservado junto con su entrada y procedencia."""

    __tablename__ = "correlations"

    __table_args__ = (
        UniqueConstraint("company_id", "id"),
        UniqueConstraint(
            "company_id",
            "request_sha256",
            name="uq_correlations_company_request",
        ),
        ForeignKeyConstraint(
            ["company_id", "dependency_id"],
            ["resource_dependencies.company_id", "resource_dependencies.id"],
        ),
        ForeignKeyConstraint(
            ["company_id", "consumer_finding_id"],
            ["findings.company_id", "findings.id"],
        ),
        ForeignKeyConstraint(
            ["company_id", "provider_finding_id"],
            ["findings.company_id", "findings.id"],
        ),
        CheckConstraint(
            "consumer_finding_id <> provider_finding_id",
            name="different_findings",
        ),
        CheckConstraint(
            "jsonb_typeof(proposal) = 'object' "
            "AND jsonb_typeof(context_snapshot) = 'object'",
            name="json_objects",
        ),
        CheckConstraint(
            "length(btrim(agent_name)) > 0 "
            "AND length(btrim(model_name)) > 0",
            name="provenance",
        ),
        CheckConstraint(
            "length(prompt_sha256) = 64 "
            "AND length(context_sha256) = 64 "
            "AND length(request_sha256) = 64",
            name="hash_lengths",
        ),
        Index(
            "ix_correlations_company_dependency",
            "company_id",
            "dependency_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(BigInteger)
    dependency_id: Mapped[int] = mapped_column(BigInteger)
    consumer_finding_id: Mapped[int] = mapped_column(BigInteger)
    provider_finding_id: Mapped[int] = mapped_column(BigInteger)

    proposal: Mapped[dict[str, Any]] = mapped_column(JSONB)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)

    agent_name: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(Text)
    prompt_sha256: Mapped[str] = mapped_column(Text)
    context_sha256: Mapped[str] = mapped_column(Text)
    request_sha256: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
    )