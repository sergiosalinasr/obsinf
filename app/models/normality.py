from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
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


class NormalityProfile(Base):
    """Una versión de un perfil de normalidad de una empresa.

    Las transiciones de estado y la inmutabilidad de versiones
    publicadas se implementarán en los servicios.
    """

    __tablename__ = "normality_profiles"

    __table_args__ = (
        UniqueConstraint("company_id", "id"),
        UniqueConstraint("company_id", "code", "version"),
        CheckConstraint(
            "length(btrim(code)) > 0 "
            "AND length(btrim(version)) > 0 "
            "AND length(btrim(name)) > 0",
            name="required_text",
        ),
        CheckConstraint(
            "profile_type = 'CONFIGURED'",
            name="profile_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="status",
        ),
        # Solo una versión activa por código dentro de cada empresa.
        Index(
            "uq_normality_profiles_active_code",
            "company_id",
            "code",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ix_normality_profiles_company_status",
            "company_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    company_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("companies.id"),
    )

    code: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)

    profile_type: Mapped[str] = mapped_column(
        Text, server_default="CONFIGURED"
    )
    status: Mapped[str] = mapped_column(
        Text, server_default="draft"
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


class NormalityRule(Base):
    """Límites configurados para una serie específica.

    dimensions y series_key serán normalizados conjuntamente
    por el servicio antes de guardar la regla.
    """

    __tablename__ = "normality_rules"

    __table_args__ = (
        # Estas relaciones impiden cruces entre empresas.
        ForeignKeyConstraint(
            ["company_id", "profile_id"],
            ["normality_profiles.company_id", "normality_profiles.id"],
        ),
        ForeignKeyConstraint(
            ["company_id", "source_id"],
            ["sources.company_id", "sources.id"],
        ),
        UniqueConstraint("company_id", "id"),
        # Nombre explícito para evitar un identificador demasiado largo.
        UniqueConstraint(
            "company_id",
            "profile_id",
            "source_id",
            "resource_key",
            "metric_name",
            "unit",
            "series_key",
            name="uq_normality_rules_series",
        ),
        CheckConstraint(
            "length(btrim(resource_key)) > 0 "
            "AND length(btrim(metric_name)) > 0 "
            "AND length(btrim(unit)) > 0 "
            "AND length(btrim(series_key)) > 0",
            name="required_text",
        ),
        CheckConstraint(
            "jsonb_typeof(dimensions) = 'object'",
            name="dimensions_object",
        ),
        CheckConstraint(
            "lower_threshold IS NOT NULL "
            "OR upper_threshold IS NOT NULL",
            name="threshold_required",
        ),
        CheckConstraint(
            "lower_threshold IS NULL OR ("
            "lower_threshold > '-Infinity'::double precision "
            "AND lower_threshold < 'Infinity'::double precision)",
            name="lower_threshold_finite",
        ),
        CheckConstraint(
            "upper_threshold IS NULL OR ("
            "upper_threshold > '-Infinity'::double precision "
            "AND upper_threshold < 'Infinity'::double precision)",
            name="upper_threshold_finite",
        ),
        CheckConstraint(
            "lower_threshold IS NULL "
            "OR upper_threshold IS NULL "
            "OR lower_threshold <= upper_threshold",
            name="threshold_order",
        ),
        CheckConstraint(
            "min_samples >= 1",
            name="min_samples_positive",
        ),
        CheckConstraint(
            "max_gap_seconds > 0 "
            "AND max_gap_seconds < 'Infinity'::double precision",
            name="max_gap_positive_finite",
        ),
        Index(
            "ix_normality_rules_company_source_metric",
            "company_id",
            "source_id",
            "metric_name",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    company_id: Mapped[int] = mapped_column(BigInteger)
    profile_id: Mapped[int] = mapped_column(BigInteger)
    source_id: Mapped[int] = mapped_column(BigInteger)

    resource_key: Mapped[str] = mapped_column(Text)
    metric_name: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(Text)

    dimensions: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        server_default=text("'{}'::jsonb"),
    )
    series_key: Mapped[str] = mapped_column(
        Text,
        server_default="{}",
    )

    lower_threshold: Mapped[float | None] = mapped_column(Double)
    upper_threshold: Mapped[float | None] = mapped_column(Double)

    min_samples: Mapped[int] = mapped_column(
        Integer,
        server_default=text("1"),
    )
    # Sin default: debe decidirse según la frecuencia de muestreo.
    max_gap_seconds: Mapped[float] = mapped_column(Double)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )