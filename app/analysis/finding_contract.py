from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class Classification(str, Enum):
    """Clasificación analítica heredada de la POC."""

    NORMAL = "NORMAL"
    EVENT = "EVENT"
    ANOMALY = "ANOMALY"
    RISK = "RISK"
    DEGRADATION = "DEGRADATION"
    INCIDENT = "INCIDENT"


class Severity(str, Enum):
    """Severidad propuesta para el hallazgo."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FindingProposal(BaseModel):
    """Propuesta del agente, que debe validarse antes de persistir.

    La empresa, fuente y ejecución se obtienen del contexto autorizado
    por OBSINF; no se confían al contenido generado por el modelo.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    resource_key: str = Field(min_length=1, max_length=500)
    start: AwareDatetime
    end: AwareDatetime

    classification: Classification
    severity: Severity

    # Es una estimación declarada por el agente, no una probabilidad
    # calibrada ni una garantía de que el hallazgo sea correcto.
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)

    finding: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[int] = Field(min_length=1, max_length=100)
    # Solo referencias; la selección autorizada de eventos la realiza Python.
    event_ids: list[Annotated[int, Field(strict=True, gt=0, le=9223372036854775807)]] = Field(
        default_factory=list, max_length=100
    )
    possible_implications: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("confidence", mode="before")
    @classmethod
    def reject_boolean_confidence(cls, value):
        if isinstance(value, bool):
            raise ValueError("La confianza debe ser numérica")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[int]) -> list[int]:
        """Exige IDs positivos y sin repeticiones."""
        if any(type(item) is not int or item <= 0 for item in value):
            raise ValueError("Los IDs de evidencia deben ser positivos")

        if len(value) != len(set(value)):
            raise ValueError("Los IDs de evidencia no pueden repetirse")

        return value

    @field_validator("event_ids")
    @classmethod
    def validate_event_ids(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("Los IDs de eventos no pueden repetirse")
        return value

    @field_validator("possible_implications")
    @classmethod
    def validate_implications(cls, value: list[str]) -> list[str]:
        """Evita implicancias vacías o excesivamente largas."""
        cleaned = [item.strip() for item in value]

        if any(not item or len(item) > 1000 for item in cleaned):
            raise ValueError("Las implicancias deben contener texto válido")

        return cleaned

    @model_validator(mode="after")
    def validate_period(self):
        if self.start > self.end:
            raise ValueError("El inicio no puede ser posterior al fin")

        return self


def validate_finding_context(
    proposal: FindingProposal,
    *,
    expected_resource: str,
    allowed_evidence_ids: set[int],
    evidence_periods: dict[int, tuple[datetime, datetime]],
) -> None:
    """Comprueba la propuesta contra el contexto entregado al agente.

    El llamador debe construir allowed_evidence_ids y evidence_periods
    desde evidencias de la empresa, ejecución y fuente autorizadas.

    Cada evidencia citada debe pertenecer al recurso analizado y
    quedar contenida en el período propuesto por el agente.
    """
    if proposal.resource_key != expected_resource:
        raise ValueError("El recurso no corresponde al contexto")

    cited_ids = set(proposal.evidence_ids)

    if not cited_ids.issubset(allowed_evidence_ids):
        raise ValueError("El hallazgo cita evidencias no disponibles")

    if not cited_ids.issubset(evidence_periods):
        raise ValueError("Faltan períodos de evidencias citadas")

    for evidence_id in cited_ids:
        start, end = evidence_periods[evidence_id]

        if (
            start.tzinfo is None
            or start.utcoffset() is None
            or end.tzinfo is None
            or end.utcoffset() is None
            or start > end
        ):
            raise ValueError("El período de la evidencia es inválido")

        if proposal.start > start or proposal.end < end:
            raise ValueError(
                "El período del hallazgo no cubre las evidencias citadas"
            )
