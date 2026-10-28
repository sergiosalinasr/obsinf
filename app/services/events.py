import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.company import Company
from app.models.observations import EventNormalized
from app.models.source import Source
from app.services.metrics import (
    MetricQueryError,
    decode_cursor,
    encode_cursor,
)


class EventQueryError(Exception):
    """Error esperado en una consulta de eventos."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def query_events(
    db: Session,
    company_id: int,
    period_start: datetime,
    period_end: datetime,
    source_id: int | None = None,
    severity: str | None = None,
    event_code: str | None = None,
    resource_key: str | None = None,
    record_type: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[EventNormalized], str | None]:
    """Consulta eventos en el intervalo [inicio, fin).

    Las empresas y fuentes inactivas conservan su consulta histórica.
    """
    if period_start.tzinfo is None or period_end.tzinfo is None:
        raise EventQueryError(
            422, "TIMEZONE_REQUIRED",
            "Las fechas deben incluir zona horaria",
        )

    start = period_start.astimezone(timezone.utc)
    end = period_end.astimezone(timezone.utc)

    if start >= end:
        raise EventQueryError(
            422, "INVALID_PERIOD", "from debe ser anterior a to"
        )

    if end - start > timedelta(days=get_settings().max_query_days):
        raise EventQueryError(
            422, "PERIOD_TOO_LARGE",
            "El período supera la ventana máxima permitida",
        )

    if db.get(Company, company_id) is None:
        raise EventQueryError(
            404, "COMPANY_NOT_FOUND", "Empresa no encontrada"
        )

    if source_id is not None:
        source = db.scalar(
            select(Source.id).where(
                Source.id == source_id,
                Source.company_id == company_id,
            )
        )

        if source is None:
            raise EventQueryError(
                404, "SOURCE_NOT_FOUND", "Fuente no encontrada"
            )

    filters = {
        "query": "events",
        "company_id": company_id,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "source_id": source_id,
        "severity": severity,
        "event_code": event_code,
        "resource_key": resource_key,
        "record_type": record_type,
    }
    scope = hashlib.sha256(
        json.dumps(
            filters, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()

    statement = select(EventNormalized).where(
        EventNormalized.company_id == company_id,
        EventNormalized.occurred_at >= start,
        EventNormalized.occurred_at < end,
    )

    # Los filtros son comparaciones exactas, sin SQL construido con texto.
    optional_filters = (
        (EventNormalized.source_id, source_id),
        (EventNormalized.severity, severity),
        (EventNormalized.event_code, event_code),
        (EventNormalized.resource_key, resource_key),
        (EventNormalized.record_type, record_type),
    )

    for column, value in optional_filters:
        if value is not None:
            statement = statement.where(column == value)

    if cursor is not None:
        try:
            last_time, last_id = decode_cursor(cursor, scope)
        except MetricQueryError as exc:
            raise EventQueryError(
                exc.status_code, exc.code, exc.message
            ) from None

        statement = statement.where(
            or_(
                EventNormalized.occurred_at > last_time,
                and_(
                    EventNormalized.occurred_at == last_time,
                    EventNormalized.id > last_id,
                ),
            )
        )

    rows = list(db.scalars(
        statement.order_by(
            EventNormalized.occurred_at,
            EventNormalized.id,
        ).limit(limit + 1)
    ).all())

    items = rows[:limit]
    next_cursor = None

    if len(rows) > limit:
        last = items[-1]
        next_cursor = encode_cursor(
            last.occurred_at, last.id, scope
        )

    return items, next_cursor