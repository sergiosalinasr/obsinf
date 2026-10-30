"""Contratos para configurar y consultar dependencias entre recursos."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PositiveId = Annotated[int, Field(strict=True, gt=0)]


class DependencyCreate(BaseModel):
    """La identidad del operador se obtiene fuera de la solicitud."""

    model_config = ConfigDict(extra="forbid")

    consumer_source_id: PositiveId
    consumer_resource_key: str = Field(
        strict=True, min_length=1, max_length=500
    )
    provider_source_id: PositiveId
    provider_resource_key: str = Field(
        strict=True, min_length=1, max_length=500
    )
    dependency_type: Literal["uses_database_service"] = (
        "uses_database_service"
    )
    description: str = Field(
        strict=True, min_length=1, max_length=2000
    )

    @field_validator(
        "consumer_resource_key",
        "provider_resource_key",
        "description",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        """Conserva identificadores exactos y evita textos vacíos."""
        if not value.strip() or value != value.strip():
            raise ValueError(
                "El texto no puede estar vacío ni tener espacios exteriores"
            )
        return value


class DependencyUpdate(BaseModel):
    """Solo permite activar o desactivar una relación existente."""

    model_config = ConfigDict(extra="forbid")

    is_active: bool = Field(strict=True)


class DependencyRead(BaseModel):
    """Representación pública de una dependencia configurada."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    consumer_source_id: int
    consumer_resource_key: str
    provider_source_id: int
    provider_resource_key: str
    dependency_type: str
    description: str
    configured_by: str
    is_active: bool
    created_at: datetime
    updated_at: datetime