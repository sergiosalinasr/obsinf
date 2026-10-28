from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class CompanyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    timezone: str = "America/Santiago"

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        value = value.strip().upper()

        if not value or any(character.isspace() for character in value):
            raise ValueError("El código no puede estar vacío ni contener espacios")

        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("El nombre no puede estar vacío")

        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("La zona horaria no es válida") from None

        return value


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    timezone: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

class CompanyUpdate(BaseModel):
    """Define los campos que pueden modificarse parcialmente."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = None
    is_active: bool | None = Field(default=None, strict=True)

    @model_validator(mode="before")
    @classmethod
    def validate_payload(cls, data):
        """Rechaza solicitudes vacías y valores nulos explícitos."""
        if isinstance(data, dict):
            if not data:
                raise ValueError("Debe indicar al menos un campo")

            for field in ("name", "timezone", "is_active"):
                if field in data and data[field] is None:
                    raise ValueError(f"El campo {field} no puede ser null")

        return data

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        """Elimina espacios externos y evita nombres vacíos."""
        if value is None:
            return value

        value = value.strip()

        if not value:
            raise ValueError("El nombre no puede estar vacío")

        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        """Comprueba que la zona horaria exista."""
        if value is None:
            return value

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("La zona horaria no es válida") from None

        return value