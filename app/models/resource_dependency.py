"""Dependencias configuradas entre recursos de una misma empresa."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResourceDependency(Base):
    """Declara que un recurso consumidor utiliza un recurso proveedor.

    Los recursos se identifican por su fuente y resource_key.
    La relación es configuración explícita, no una conclusión del agente.
    """

    __tablename__ = "resource_dependencies"

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "id",
            name="uq_resource_dependencies_company_id_id",
        ),
        UniqueConstraint(
            "company_id",
            "consumer_source_id",
            "consumer_resource_key",
            "provider_source_id",
            "provider_resource_key",
            "dependency_type",
            name="uq_resource_dependencies_relationship",
        ),
        # Ambas fuentes deben pertenecer a la empresa de la relación.
        ForeignKeyConstraint(
            ["company_id", "consumer_source_id"],
            ["sources.company_id", "sources.id"],
            name="fk_resource_dependencies_consumer",
        ),
        ForeignKeyConstraint(
            ["company_id", "provider_source_id"],
            ["sources.company_id", "sources.id"],
            name="fk_resource_dependencies_provider",
        ),
        CheckConstraint(
            "length(btrim(consumer_resource_key)) > 0",
            name="consumer_resource_not_empty",
        ),
        CheckConstraint(
            "length(btrim(provider_resource_key)) > 0",
            name="provider_resource_not_empty",
        ),
        CheckConstraint(
            "dependency_type IN ('uses_database_service')",
            name="dependency_type",
        ),
        CheckConstraint(
            "length(btrim(description)) > 0",
            name="description_not_empty",
        ),
        CheckConstraint(
            "length(btrim(configured_by)) > 0",
            name="configured_by_not_empty",
        ),
        # Una fuente puede contener varios recursos relacionados,
        # pero un recurso no puede depender de sí mismo.
        CheckConstraint(
            "consumer_source_id <> provider_source_id "
            "OR consumer_resource_key <> provider_resource_key",
            name="different_resources",
        ),
        Index(
            "ix_resource_dependencies_company_provider",
            "company_id",
            "provider_source_id",
            "provider_resource_key",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    company_id: Mapped[int] = mapped_column(BigInteger)

    consumer_source_id: Mapped[int] = mapped_column(BigInteger)
    consumer_resource_key: Mapped[str] = mapped_column(Text)

    provider_source_id: Mapped[int] = mapped_column(BigInteger)
    provider_resource_key: Mapped[str] = mapped_column(Text)

    dependency_type: Mapped[str] = mapped_column(
        Text,
        server_default="uses_database_service",
    )
    description: Mapped[str] = mapped_column(Text)
    configured_by: Mapped[str] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )