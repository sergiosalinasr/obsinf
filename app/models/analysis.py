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
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnalysisExecution(Base):
    """Ejecución de análisis de un perfil sobre un período."""

    __tablename__ = "analysis_executions"

    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "profile_id"],
            ["normality_profiles.company_id", "normality_profiles.id"],
        ),
        UniqueConstraint("company_id", "id"),
        CheckConstraint(
            "period_start < period_end",
            name="period_order",
        ),
        CheckConstraint(
            "status IN ('processing', 'completed', 'partial', 'failed')",
            name="status",
        ),
        Index(
            "ix_analysis_executions_company_started",
            "company_id",
            "started_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(BigInteger)
    profile_id: Mapped[int] = mapped_column(BigInteger)

    # Copia para facilitar la interpretación histórica.
    profile_code: Mapped[str] = mapped_column(Text)
    profile_version: Mapped[str] = mapped_column(Text)
    detector_version: Mapped[str] = mapped_column(Text)

    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Instante hasta el cual se consideran datos recibidos.
    data_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    status: Mapped[str] = mapped_column(
        Text, server_default="processing"
    )
    coverage: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    error_summary: Mapped[str | None] = mapped_column(Text)


class Evidence(Base):
    """Evidencia determinista producida por una regla de normalidad."""

    __tablename__ = "evidence"

    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "execution_id"],
            ["analysis_executions.company_id", "analysis_executions.id"],
        ),
        ForeignKeyConstraint(
            ["company_id", "rule_id"],
            ["normality_rules.company_id", "normality_rules.id"],
        ),
        ForeignKeyConstraint(
            ["company_id", "source_id"],
            ["sources.company_id", "sources.id"],
        ),
        UniqueConstraint("company_id", "id"),
        CheckConstraint(
            "comparison IN "
            "('below_lower_threshold', 'above_upper_threshold')",
            name="comparison",
        ),
        CheckConstraint(
            "start_at <= end_at",
            name="period_order",
        ),
        CheckConstraint(
            "sample_count >= 1 AND duration_seconds >= 0",
            name="samples_and_duration",
        ),
        Index(
            "ix_evidence_company_execution",
            "company_id",
            "execution_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(BigInteger)
    execution_id: Mapped[int] = mapped_column(BigInteger)
    rule_id: Mapped[int] = mapped_column(BigInteger)
    source_id: Mapped[int] = mapped_column(BigInteger)

    evidence_type: Mapped[str] = mapped_column(Text)
    resource_key: Mapped[str] = mapped_column(Text)
    metric_name: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(Text)
    series_key: Mapped[str] = mapped_column(Text)

    comparison: Mapped[str] = mapped_column(Text)
    threshold_value: Mapped[float] = mapped_column(Double)
    min_observed: Mapped[float] = mapped_column(Double)
    max_observed: Mapped[float] = mapped_column(Double)

    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float] = mapped_column(Double)
    sample_count: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class EvidenceMetric(Base):
    """Asocia una evidencia a las mediciones que la sustentan."""

    __tablename__ = "evidence_metrics"

    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "evidence_id"],
            ["evidence.company_id", "evidence.id"],
        ),
        ForeignKeyConstraint(
            ["company_id", "metric_id"],
            ["metrics_normalized.company_id", "metrics_normalized.id"],
        ),
        UniqueConstraint("company_id", "evidence_id", "metric_id"),
        Index(
            "ix_evidence_metrics_company_evidence",
            "company_id",
            "evidence_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(BigInteger)
    evidence_id: Mapped[int] = mapped_column(BigInteger)
    metric_id: Mapped[int] = mapped_column(BigInteger)