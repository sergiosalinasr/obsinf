from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class Source(Base):
    __tablename__ = "sources"

    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        UniqueConstraint("company_id", "id"),
        CheckConstraint(
            "ingestion_method IN ('file', 'api', 'collector')",
            name="ingestion_method",
        ),
        Index("ix_sources_company_technology", "company_id", "technology_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id")
    )
    technology_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("technologies.id")
    )
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    environment: Mapped[str] = mapped_column(
        Text, server_default="unspecified"
    )
    ingestion_method: Mapped[str] = mapped_column(
        Text, server_default="file"
    )
    source_timezone: Mapped[str] = mapped_column(Text)
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    secret_ref: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )