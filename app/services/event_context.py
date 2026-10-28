"""Recuperación de eventos cercanos a evidencias métricas de WebLogic."""

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.analysis.event_context import ContextEvent, EventContext, EventWindow
from app.models.analysis import AnalysisExecution, Evidence
from app.models.observations import EventNormalized
from app.models.source import Source
from app.models.technology import Technology


def load_event_context(
    db: Session,
    *,
    company_id: int,
    execution_id: int,
    source_id: int,
    resource_key: str,
    evidence_ids: list[int],
    margin_seconds: int = 120,
    event_limit: int = 100,
    max_message_chars: int = 2000,
) -> EventContext:
    """Selecciona eventos sin abrir una ventana continua entre evidencias lejanas.

    Solo considera datos recibidos hasta el corte de la ejecución. Ordena
    cronológicamente; una fila extra detecta si se omitieron eventos por límite.
    No filtra por severidad: un mensaje informativo también puede ser relevante.
    """
    if (
        any(type(v) is not int or v <= 0 for v in (company_id, execution_id, source_id))
        or not resource_key.strip()
        or not evidence_ids
        or len(evidence_ids) > 1000
        or any(type(v) is not int or v <= 0 for v in evidence_ids)
        or len(evidence_ids) != len(set(evidence_ids))
        or type(margin_seconds) is not int or not 0 <= margin_seconds <= 3600
        or type(event_limit) is not int or not 1 <= event_limit <= 100
        or type(max_message_chars) is not int or not 1 <= max_message_chars <= 4000
    ):
        raise ValueError("Parámetros del contexto de eventos inválidos")

    execution = db.scalar(select(AnalysisExecution).where(
        AnalysisExecution.company_id == company_id,
        AnalysisExecution.id == execution_id,
    ))
    if execution is None or execution.status not in ("completed", "partial"):
        raise ValueError("Ejecución no disponible en la empresa")
    source = db.scalar(select(Source.id).join(
        Technology, Source.technology_id == Technology.id
    ).where(
        Source.company_id == company_id, Source.id == source_id,
        Technology.code == "weblogic",
    ))
    if source is None:
        raise ValueError("Fuente WebLogic no encontrada en la empresa")

    evidence = list(db.scalars(select(Evidence).where(
        Evidence.company_id == company_id,
        Evidence.execution_id == execution_id,
        Evidence.source_id == source_id,
        Evidence.resource_key == resource_key,
        Evidence.id.in_(evidence_ids),
    ).order_by(Evidence.start_at, Evidence.id)).all())
    if {row.id for row in evidence} != set(evidence_ids):
        raise ValueError("Las evidencias no pertenecen al contexto autorizado")

    margin = timedelta(seconds=margin_seconds)
    windows = tuple(EventWindow(
        evidence_id=row.id, start=row.start_at - margin, end=row.end_at + margin
    ) for row in evidence)
    # SQL usa la unión de ventanas; un evento que cae en dos aparece una sola vez.
    in_window = or_(*[
        EventNormalized.occurred_at.between(window.start, window.end)
        for window in windows
    ])
    rows = list(db.scalars(select(EventNormalized).where(
        EventNormalized.company_id == company_id,
        EventNormalized.source_id == source_id,
        EventNormalized.resource_key == resource_key,
        EventNormalized.received_at <= execution.data_cutoff_at,
        in_window,
    ).order_by(EventNormalized.occurred_at, EventNormalized.id).limit(event_limit + 1)).all())

    return EventContext(
        company_id=company_id,
        execution_id=execution_id,
        source_id=source_id,
        resource_key=resource_key,
        data_cutoff_at=execution.data_cutoff_at,
        margin_seconds=margin_seconds,
        event_limit=event_limit,
        max_message_chars=max_message_chars,
        windows=windows,
        has_more_events=len(rows) > event_limit,
        events=tuple(ContextEvent(
            id=row.id, resource_key=row.resource_key, record_type=row.record_type,
            severity=row.severity, event_code=row.event_code,
            occurred_at=row.occurred_at, received_at=row.received_at,
            message=row.message[:max_message_chars],
            message_truncated=len(row.message) > max_message_chars,
        ) for row in rows[:event_limit]),
    )
