from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceCreate(BaseModel):
    """Datos para registrar una fuente de archivos.

    La empresa se obtiene de la URL, no del cuerpo de la solicitud.
    La configuración avanzada se incorporará con los adaptadores.
    """

    model_config = ConfigDict(extra="forbid")

    technology_id: int = Field(gt=0)
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    environment: str = Field(
        default="unspecified", min_length=1, max_length=50
    )
    ingestion_method: Literal["file"] = "file"
    source_timezone: str = "America/Santiago"

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        """Normaliza el código y rechaza espacios internos."""
        value = value.strip().upper()

        if not value or any(character.isspace() for character in value):
            raise ValueError("El código no puede estar vacío ni contener espacios")

        return value

    @field_validator("name", "environment")
    @classmethod
    def validate_text(cls, value: str) -> str:
        """Evita textos formados únicamente por espacios."""
        value = value.strip()

        if not value:
            raise ValueError("El campo no puede estar vacío")

        return value

    @field_validator("source_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """Comprueba que la zona horaria exista."""
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("La zona horaria no es válida") from None

        return value


class SourceRead(BaseModel):
    """Información pública de una fuente, sin referencias a secretos."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    technology_id: int
    code: str
    name: str
    environment: str
    ingestion_method: str
    source_timezone: str
    is_active: bool
    created_at: datetime
    updated_at: datetime