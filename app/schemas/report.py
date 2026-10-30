"""Solicitud de generación manual de un reporte."""

from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


PositiveId = Annotated[int, Field(strict=True, gt=0)]


class ReportRequest(BaseModel):
    """Selección explícita de resultados existentes."""

    model_config = ConfigDict(extra="forbid")

    period_start: AwareDatetime
    period_end: AwareDatetime
    timezone: str = Field(min_length=1, max_length=100)

    finding_ids: list[PositiveId] = Field(
        default_factory=list, max_length=100
    )
    correlation_ids: list[PositiveId] = Field(
        default_factory=list, max_length=100
    )

    @field_validator("finding_ids", "correlation_ids")
    @classmethod
    def unique_ids(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Los IDs no pueden repetirse")
        return values

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Zona horaria inválida") from None
        return value

    @model_validator(mode="after")
    def valid_request(self):
        if self.period_start >= self.period_end:
            raise ValueError("El inicio debe ser anterior al fin")

        if not self.finding_ids and not self.correlation_ids:
            raise ValueError(
                "Selecciona al menos un hallazgo o una correlación"
            )

        return self