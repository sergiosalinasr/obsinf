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


class MetricNormalized(Base):
    """Una medición normalizada de un recurso en un instante."""

    __tablename__ = "metrics_normalized"

    __table_args__ = (
        # El lote debe pertenecer a la empresa y fuente indicadas.
        ForeignKeyConstraint(
            ["company_id", "source_id", "batch_id"],
            [
                "ingestion_batches.company_id",
                "ingestion_batches.source_id",
                "ingestion_batches.id",
            ],
        ),
        # Cuando hay archivo, debe pertenecer al mismo lote.
        ForeignKeyConstraint(
            ["company_id", "batch_id", "file_id"],
            [
                "ingestion_files.company_id",
                "ingestion_files.batch_id",
                "ingestion_files.id",
            ],
        ),
        UniqueConstraint("company_id", "id"),
        UniqueConstraint("company_id", "source_id", "dedup_key"),
        CheckConstraint(
            "value > '-Infinity'::double precision "
            "AND value < 'Infinity'::double precision",
            name="value_finite",
        ),
        Index(
            "ix_metrics_normalized_source_metric_time",
            "company_id",
            "source_id",
            "metric_name",
            "observed_at",
        ),
        Index(
            "ix_metrics_normalized_company_time",
            "company_id",
            "observed_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(BigInteger)
    source_id: Mapped[int] = mapped_column(BigInteger)
    batch_id: Mapped[int] = mapped_column(BigInteger)
    file_id: Mapped[int | None] = mapped_column(BigInteger)

    record_locator: Mapped[str | None] = mapped_column(Text)
    resource_key: Mapped[str] = mapped_column(Text)
    metric_name: Mapped[str] = mapped_column(Text)
    value: Mapped[float] = mapped_column(Double)
    unit: Mapped[str] = mapped_column(Text)

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    dedup_key: Mapped[str] = mapped_column(Text)


class EventNormalized(Base):
    """Un evento o registro de log interpretado y normalizado."""

    __tablename__ = "events_normalized"

    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "source_id", "batch_id"],
            [
                "ingestion_batches.company_id",
                "ingestion_batches.source_id",
                "ingestion_batches.id",
            ],
        ),
        ForeignKeyConstraint(
            ["company_id", "batch_id", "file_id"],
            [
                "ingestion_files.company_id",
                "ingestion_files.batch_id",
                "ingestion_files.id",
            ],
        ),
        UniqueConstraint("company_id", "id"),
        UniqueConstraint("company_id", "source_id", "dedup_key"),
        CheckConstraint(
            "record_type IN ('event', 'log')",
            name="record_type",
        ),
        CheckConstraint(
            "severity IN "
            "('unknown', 'debug', 'info', 'warning', 'error', 'critical')",
            name="severity",
        ),
        Index(
            "ix_events_normalized_source_time",
            "company_id",
            "source_id",
            "occurred_at",
        ),
        Index(
            "ix_events_normalized_company_time",
            "company_id",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(BigInteger)
    source_id: Mapped[int] = mapped_column(BigInteger)
    batch_id: Mapped[int] = mapped_column(BigInteger)
    file_id: Mapped[int | None] = mapped_column(BigInteger)

    record_locator: Mapped[str | None] = mapped_column(Text)
    resource_key: Mapped[str] = mapped_column(Text)
    record_type: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    original_severity: Mapped[str | None] = mapped_column(Text)
    event_code: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    dedup_key: Mapped[str] = mapped_column(Text)