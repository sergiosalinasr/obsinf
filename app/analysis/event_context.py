"""Contrato del contexto de eventos seleccionado por Python, no por el LLM."""

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.analysis.finding_contract import FindingProposal


PositiveId = Annotated[int, Field(strict=True, gt=0, le=9223372036854775807)]


class EventWindow(BaseModel):
    """Ventana inclusiva alrededor de una evidencia concreta."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    evidence_id: PositiveId
    start: AwareDatetime
    end: AwareDatetime


class ContextEvent(BaseModel):
    """Copia acotada de un evento normalizado tal como se envía al agente."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: PositiveId
    resource_key: str
    record_type: str
    severity: str
    event_code: str | None
    occurred_at: AwareDatetime
    received_at: AwareDatetime
    message: str
    message_truncated: bool


class EventContext(BaseModel):
    """Selección reproducible y acotada de eventos para un recurso.

    Se conserva completa con el hallazgo, incluyendo los mensajes recortados
    que recibió el agente. Ningún campo de este objeto proviene del LLM.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    company_id: PositiveId
    execution_id: PositiveId
    source_id: PositiveId
    resource_key: str
    data_cutoff_at: AwareDatetime
    margin_seconds: int = Field(ge=0, le=3600)
    event_limit: int = Field(ge=1, le=100)
    max_message_chars: int = Field(ge=1, le=4000)
    windows: tuple[EventWindow, ...] = Field(min_length=1)
    events: tuple[ContextEvent, ...] = ()
    has_more_events: bool = False

    @model_validator(mode="after")
    def validate_selection(self):
        if any(w.start > w.end for w in self.windows):
            raise ValueError("Ventana de eventos inválida")
        evidence_ids = [w.evidence_id for w in self.windows]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Las ventanas repiten evidencias")
        ids = [event.id for event in self.events]
        if len(ids) != len(set(ids)) or len(ids) > self.event_limit:
            raise ValueError("Selección de eventos inválida")
        if list(self.events) != sorted(self.events, key=lambda e: (e.occurred_at, e.id)):
            raise ValueError("Los eventos deben estar ordenados por instante e ID")
        for event in self.events:
            if event.resource_key != self.resource_key:
                raise ValueError("El evento no corresponde al recurso")
            if event.received_at > self.data_cutoff_at:
                raise ValueError("El evento es posterior al corte de recepción")
            if not any(w.start <= event.occurred_at <= w.end for w in self.windows):
                raise ValueError("El evento está fuera de las ventanas")
            if len(event.message) > self.max_message_chars:
                raise ValueError("El mensaje excede el límite del contexto")
        return self


def validate_event_citations(proposal: FindingProposal, context: EventContext | None) -> None:
    """No permite citar eventos ausentes ni vinculados solo a evidencias omitidas."""
    if context is None:
        if proposal.event_ids:
            raise ValueError("El hallazgo cita eventos no disponibles")
        return
    if context.resource_key != proposal.resource_key:
        raise ValueError("El contexto de eventos no corresponde al recurso")
    by_id = {event.id: event for event in context.events}
    if not set(proposal.event_ids).issubset(by_id):
        raise ValueError("El hallazgo cita eventos no disponibles")
    windows = [w for w in context.windows if w.evidence_id in proposal.evidence_ids]
    for event_id in proposal.event_ids:
        event = by_id[event_id]
        if not any(w.start <= event.occurred_at <= w.end for w in windows):
            raise ValueError("El evento no es cercano a las evidencias citadas")
        if not proposal.start <= event.occurred_at <= proposal.end:
            raise ValueError("El período del hallazgo no cubre los eventos citados")
