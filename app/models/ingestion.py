from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class IngestionBatch(Base):
    """Registra una solicitud de carga y su procesamiento.

    La clave de idempotencia evita repetir solicitudes.
    El token y el heartbeat permiten controlar quién procesa el lote.
    """

    __tablename__ = "ingestion_batches"

    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "source_id"],
            ["sources.company_id", "sources.id"],
        ),
        UniqueConstraint("company_id", "id"),
        # Permite que las observaciones verifiquen también la fuente.
        UniqueConstraint("company_id", "source_id", "id"),
        UniqueConstraint("company_id", "source_id", "idempotency_key"),
        CheckConstraint(
            "status IN "
            "('pending', 'processing', 'completed', 'partial', 'failed')",
            name="status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="attempt_count_nonnegative",
        ),
        CheckConstraint(
            "records_read >= 0 AND records_accepted >= 0 "
            "AND records_rejected >= 0 AND records_duplicate >= 0",
            name="counters_nonnegative",
        ),
        Index(
            "ix_ingestion_batches_company_received",
            "company_id",
            text("received_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id")
    )
    source_id: Mapped[int] = mapped_column(BigInteger)

    idempotency_key: Mapped[str] = mapped_column(Text)
    request_fingerprint: Mapped[str] = mapped_column(Text)
    request_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)

    status: Mapped[str] = mapped_column(
        Text, server_default="pending"
    )
    parser_version: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(Text)

    processing_token: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, server_default=text("0")
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    records_read: Mapped[int] = mapped_column(
        BigInteger, server_default=text("0")
    )
    records_accepted: Mapped[int] = mapped_column(
        BigInteger, server_default=text("0")
    )
    records_rejected: Mapped[int] = mapped_column(
        BigInteger, server_default=text("0")
    )
    records_duplicate: Mapped[int] = mapped_column(
        BigInteger, server_default=text("0")
    )
    error_summary: Mapped[str | None] = mapped_column(Text)


class IngestionFile(Base):
    """Describe un archivo original y su ubicación de almacenamiento."""

    __tablename__ = "ingestion_files"

    __table_args__ = (
        # Impide asociar un archivo al lote de otra empresa.
        ForeignKeyConstraint(
            ["company_id", "batch_id"],
            ["ingestion_batches.company_id", "ingestion_batches.id"],
        ),
        UniqueConstraint("company_id", "id"),
        # Permite verificar que errores y observaciones usen el mismo lote.
        UniqueConstraint("company_id", "batch_id", "id"),
        UniqueConstraint("company_id", "storage_key"),
        CheckConstraint(
            "size_bytes >= 0",
            name="size_nonnegative",
        ),
        CheckConstraint(
            "status IN "
            "('received', 'processing', 'processed', 'partial', 'rejected')",
            name="status",
        ),
        Index(
            "ix_ingestion_files_company_batch",
            "company_id",
            "batch_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id")
    )
    batch_id: Mapped[int] = mapped_column(BigInteger)

    original_filename: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        Text, server_default="received"
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    error_summary: Mapped[str | None] = mapped_column(Text)


class IngestionError(Base):
    """Identifica un error de ingesta sin copiar datos sensibles."""

    __tablename__ = "ingestion_errors"

    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "batch_id"],
            ["ingestion_batches.company_id", "ingestion_batches.id"],
        ),
        # Si file_id está informado, debe pertenecer al mismo lote.
        ForeignKeyConstraint(
            ["company_id", "batch_id", "file_id"],
            [
                "ingestion_files.company_id",
                "ingestion_files.batch_id",
                "ingestion_files.id",
            ],
        ),
        Index(
            "ix_ingestion_errors_company_batch",
            "company_id",
            "batch_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id")
    )
    batch_id: Mapped[int] = mapped_column(BigInteger)
    file_id: Mapped[int | None] = mapped_column(BigInteger)

    record_locator: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )