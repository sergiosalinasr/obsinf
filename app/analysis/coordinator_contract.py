"""Contrato de correlación entre los dos extremos de una dependencia."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

PositiveId = Annotated[int, Field(strict=True, gt=0)]


class EvidenceOverlap(BaseModel):
    """Pareja de evidencias con ventanas temporales coincidentes."""

    model_config = ConfigDict(extra="forbid")

    consumer_evidence_id: PositiveId
    provider_evidence_id: PositiveId


class CorrelationProposal(BaseModel):
    """Respuesta del coordinador antes de cualquier persistencia.

    La empresa y las ejecuciones se obtienen del contexto autorizado,
    no de identificadores adicionales generados por el modelo.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    dependency_id: PositiveId
    finding_ids: list[PositiveId] = Field(min_length=2, max_length=2)
    evidence_ids: list[PositiveId] = Field(min_length=2, max_length=200)
    event_ids: list[PositiveId] = Field(default_factory=list, max_length=200)

    assessment: Literal[
        "TEMPORAL_COINCIDENCE",
        "NO_TEMPORAL_COINCIDENCE",
    ]
    causality: Literal["NOT_ESTABLISHED"]

    confidence: float = Field(
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    summary: str = Field(min_length=1, max_length=4000)

    evidence_overlaps: list[EvidenceOverlap] = Field(
        default_factory=list,
        max_length=10000,
    )
    limitations: list[str] = Field(min_length=1, max_length=20)

    @field_validator("confidence", mode="before")
    @classmethod
    def numeric_confidence(cls, value):
        """Rechaza booleanos y números enviados como texto."""
        if type(value) not in (int, float):
            raise ValueError("confidence debe ser un número")
        return value

    @field_validator("finding_ids", "evidence_ids", "event_ids")
    @classmethod
    def unique_ids(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Los IDs no pueden repetirse")
        return values

    @field_validator("limitations")
    @classmethod
    def valid_limitations(cls, values):
        cleaned = [value.strip() for value in values]

        if any(not value or len(value) > 1000 for value in cleaned):
            raise ValueError(
                "Cada limitación debe contener entre 1 y 1000 caracteres"
            )

        if len(cleaned) != len(set(cleaned)):
            raise ValueError("Las limitaciones no pueden repetirse")

        return cleaned


def _instant(value: str) -> datetime:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("El contexto contiene una fecha sin zona horaria")

    return instant


def expected_evidence_overlaps(context: dict) -> set[tuple[int, int]]:
    """Calcula coincidencias entre ventanas de evidencias individuales.

    Los extremos representan la primera y última muestra.
    Compartir una ventana no demuestra mediciones continuas ni causalidad.
    """
    overlaps = set()

    for consumer in context["consumer"]["evidence"]:
        for provider in context["provider"]["evidence"]:
            start = max(
                _instant(consumer["start_at"]),
                _instant(provider["start_at"]),
            )
            end = min(
                _instant(consumer["end_at"]),
                _instant(provider["end_at"]),
            )

            # Incluye coincidencias puntuales de muestras.
            if start <= end:
                overlaps.add((consumer["id"], provider["id"]))

    return overlaps


def validate_correlation_context(
    proposal: CorrelationProposal,
    context: dict,
) -> None:
    """Comprueba una propuesta contra build_dependency_context.

    context debe proceder del servicio de selección de OBSINF.
    No sustituye la autorización ni valida un contexto externo arbitrario.
    """
    if context.get("schema_version") != "dependency_context:1.0":
        raise ValueError("Versión de contexto no soportada")

    if proposal.dependency_id != context["dependency"]["id"]:
        raise ValueError("La dependencia no pertenece al contexto")

    sides = (context["consumer"], context["provider"])

    expected_findings = {
        side["finding"]["id"]
        for side in sides
    }
    if set(proposal.finding_ids) != expected_findings:
        raise ValueError("Deben citarse ambos hallazgos del contexto")

    expected_evidence = {
        evidence["id"]
        for side in sides
        for evidence in side["evidence"]
    }
    if set(proposal.evidence_ids) != expected_evidence:
        raise ValueError(
            "Deben citarse todas las evidencias del contexto, sin agregar otras"
        )

    allowed_events = {
        event_id
        for side in sides
        for event_id in side["finding"]["event_ids"]
    }
    if not set(proposal.event_ids).issubset(allowed_events):
        raise ValueError("Un evento citado no pertenece al contexto")

    actual_pairs = [
        (item.consumer_evidence_id, item.provider_evidence_id)
        for item in proposal.evidence_overlaps
    ]
    if len(actual_pairs) != len(set(actual_pairs)):
        raise ValueError("Las parejas de evidencias no pueden repetirse")

    expected_pairs = expected_evidence_overlaps(context)

    if set(actual_pairs) != expected_pairs:
        raise ValueError(
            "Las coincidencias no corresponden a las ventanas de evidencia"
        )

    expected_assessment = (
        "TEMPORAL_COINCIDENCE"
        if expected_pairs
        else "NO_TEMPORAL_COINCIDENCE"
    )
    if proposal.assessment != expected_assessment:
        raise ValueError(
            "La evaluación temporal contradice las evidencias"
        )


def parse_correlation_response(
    response_text: str,
    context: dict,
) -> CorrelationProposal:
    """Acepta únicamente JSON del contrato y referencias autorizadas."""
    proposal = CorrelationProposal.model_validate_json(response_text)
    validate_correlation_context(proposal, context)
    return proposal