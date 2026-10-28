import math
from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class ProfileCreate(BaseModel):
    """Datos necesarios para crear una versión en borrador."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class RuleCreate(BaseModel):
    """Regla de normalidad asociada a una fuente de la empresa."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: int = Field(gt=0)
    resource_key: str = Field(min_length=1, max_length=500)
    metric_name: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=50)

    dimensions: dict[str, Any] = Field(default_factory=dict)

    lower_threshold: float | None = None
    upper_threshold: float | None = None
    min_samples: int = Field(default=1, ge=1, strict=True)
    max_gap_seconds: float = Field(gt=0)

    @field_validator(
        "lower_threshold",
        "upper_threshold",
        "max_gap_seconds",
        mode="before",
    )
    @classmethod
    def reject_boolean_numbers(cls, value):
        """Evita interpretar true o false como números."""
        if isinstance(value, bool):
            raise ValueError("Debe ser un número, no un booleano")
        return value

    @field_validator(
        "lower_threshold",
        "upper_threshold",
        "max_gap_seconds",
    )
    @classmethod
    def require_finite(cls, value):
        """Rechaza NaN e infinitos."""
        if value is not None and not math.isfinite(value):
            raise ValueError("El valor debe ser finito")
        return value

    @model_validator(mode="after")
    def validate_thresholds(self):
        """Requiere al menos un límite y verifica su orden."""
        if self.lower_threshold is None and self.upper_threshold is None:
            raise ValueError("Debe indicar al menos un límite")

        if (
            self.lower_threshold is not None
            and self.upper_threshold is not None
            and self.lower_threshold > self.upper_threshold
        ):
            raise ValueError("El límite inferior supera al superior")

        return self

class RuleRead(BaseModel):
    """Regla configurada, incluida su identidad de serie."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    profile_id: int
    source_id: int
    resource_key: str
    metric_name: str
    unit: str
    dimensions: dict[str, Any]
    series_key: str
    lower_threshold: float | None
    upper_threshold: float | None
    min_samples: int
    max_gap_seconds: float
    created_at: datetime
    updated_at: datetime


class ProfileRead(BaseModel):
    """Versión de un perfil, sin incluir sus reglas."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    code: str
    version: str
    name: str
    description: str | None
    profile_type: str
    status: str
    created_at: datetime
    updated_at: datetime


class ProfileDetail(ProfileRead):
    """Perfil y reglas que pertenecen a la misma empresa."""

    rules: list[RuleRead]