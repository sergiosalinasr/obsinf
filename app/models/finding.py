from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKeyConstraint,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Finding(Base):
    """Interpretación de evidencias producida para una ejecución.

    La confianza es una estimación declarada por el agente;
    no representa una probabilidad calibrada.
    """

    __tablename__ = "findings"

    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(event_context) = 'object'",
            name="event_context_object",
        ),
        ForeignKeyConstraint(
            ["company_id", "execution_id"],
            ["analysis_executions.company_id", "analysis_executions.id"],
        ),
        ForeignKeyConstraint(
            ["company_id", "source_id"],
            ["sources.company_id", "sources.id"],
        ),
        UniqueConstraint("company_id", "id"),
        CheckConstraint(
            "classification IN "
            "('NORMAL', 'EVENT', 'ANOMALY', 'RISK', "
            "'DEGRADATION', 'INCIDENT')",
            name="classification",
        ),
        CheckConstraint(
            "severity IN ('INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="severity",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="confidence_range",
        ),
        CheckConstraint(
            "start_at <= end_at",
            name="period_order",
        ),
        CheckConstraint(
            "length(btrim(resource_key)) > 0 "
            "AND length(btrim(finding)) > 0",
            name="required_text",
        ),
        CheckConstraint(
            "jsonb_typeof(possible_implications) = 'array'",
            name="implications_array",
        ),
        Index(
            "ix_findings_company_execution",
            "company_id",
            "execution_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )

    company_id: Mapped[int] = mapped_column(BigInteger)
    execution_id: Mapped[int] = mapped_column(BigInteger)
    source_id: Mapped[int] = mapped_column(BigInteger)

    resource_key: Mapped[str] = mapped_column(Text)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    classification: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Double)

    finding: Mapped[str] = mapped_column(Text)
    possible_implications: Mapped[list[Any]] = mapped_column(
        JSONB,
        server_default=text("'[]'::jsonb"),
    )

    # Copia de la selección que recibió el agente; {} para hallazgos anteriores.
    event_context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )

    # Datos necesarios para saber cómo se produjo la interpretación.
    agent_name: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(Text)
    prompt_sha256: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
    )


class FindingEvidence(Base):
    """Vincula un hallazgo con una evidencia que lo sustenta."""

    __tablename__ = "finding_evidence"

    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "finding_id"],
            ["findings.company_id", "findings.id"],
        ),
        ForeignKeyConstraint(
            ["company_id", "evidence_id"],
            ["evidence.company_id", "evidence.id"],
        ),
        UniqueConstraint("company_id", "finding_id", "evidence_id"),
        Index(
            "ix_finding_evidence_company_finding",
            "company_id",
            "finding_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )

    company_id: Mapped[int] = mapped_column(BigInteger)
    finding_id: Mapped[int] = mapped_column(BigInteger)
    evidence_id: Mapped[int] = mapped_column(BigInteger)


class FindingEvent(Base):
    """Eventos normalizados citados por el agente para sustentar el hallazgo."""

    __tablename__ = "finding_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "finding_id"],
            ["findings.company_id", "findings.id"],
            name="fk_finding_events_company_finding",
        ),
        ForeignKeyConstraint(
            ["company_id", "event_id"],
            ["events_normalized.company_id", "events_normalized.id"],
            name="fk_finding_events_company_event",
        ),
        UniqueConstraint(
            "company_id", "finding_id", "event_id",
            name="uq_finding_events_company_finding_event",
        ),
        Index("ix_finding_events_company_finding", "company_id", "finding_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(BigInteger)
    finding_id: Mapped[int] = mapped_column(BigInteger)
    event_id: Mapped[int] = mapped_column(BigInteger)
