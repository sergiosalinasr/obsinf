import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.company import Company
from app.models.observations import MetricNormalized
from app.models.source import Source


class MetricQueryError(Exception):
    """Error esperado de validación o pertenencia de recursos."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def encode_cursor(observed_at: datetime, metric_id: int, scope: str) -> str:
    """Codifica la posición y la huella de los filtros de la consulta."""
    payload = {
        "v": 1,
        "time": observed_at.astimezone(timezone.utc).isoformat(),
        "id": metric_id,
        "scope": scope,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, scope: str) -> tuple[datetime, int]:
    """Rechaza cursores inválidos o reutilizados con otros filtros.

    El cursor es un mecanismo de paginación; no otorga autorización.
    El filtro obligatorio de empresa se aplica siempre en SQL.
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(
            padded, altchars=b"-_", validate=True
        )
        payload = json.loads(raw)

        if payload["v"] != 1 or payload["scope"] != scope:
            raise ValueError("Cursor incompatible")

        instant = datetime.fromisoformat(payload["time"])
        metric_id = payload["id"]

        if (
            instant.tzinfo is None
            or type(metric_id) is not int
            or metric_id <= 0
        ):
            raise ValueError("Posición inválida")

        return instant.astimezone(timezone.utc), metric_id

    except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
        raise MetricQueryError(
            422, "INVALID_CURSOR",
            "Cursor inválido o incompatible con los filtros",
        ) from None


def query_metrics(
    db: Session,
    company_id: int,
    period_start: datetime,
    period_end: datetime,
    source_id: int | None = None,
    metric_name: str | None = None,
    resource_key: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[MetricNormalized], str | None]:
    """Consulta un período [inicio, fin), ordenado por instante e ID."""
    if (
        period_start.tzinfo is None
        or period_end.tzinfo is None
    ):
        raise MetricQueryError(
            422, "TIMEZONE_REQUIRED",
            "Las fechas deben incluir zona horaria",
        )

    start = period_start.astimezone(timezone.utc)
    end = period_end.astimezone(timezone.utc)

    if start >= end:
        raise MetricQueryError(
            422, "INVALID_PERIOD",
            "from debe ser anterior a to",
        )

    if end - start > timedelta(days=get_settings().max_query_days):
        raise MetricQueryError(
            422, "PERIOD_TOO_LARGE",
            "El período supera la ventana máxima permitida",
        )

    if db.get(Company, company_id) is None:
        raise MetricQueryError(
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
            raise MetricQueryError(
                404, "SOURCE_NOT_FOUND", "Fuente no encontrada"
            )

    # La huella vincula el cursor a la empresa y a los filtros.
    # limit puede cambiar al continuar la consulta.
    filters = {
        "company_id": company_id,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "source_id": source_id,
        "metric_name": metric_name,
        "resource_key": resource_key,
    }
    scope = hashlib.sha256(
        json.dumps(
            filters, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()

    statement = select(MetricNormalized).where(
        MetricNormalized.company_id == company_id,
        MetricNormalized.observed_at >= start,
        MetricNormalized.observed_at < end,
    )

    if source_id is not None:
        statement = statement.where(
            MetricNormalized.source_id == source_id
        )

    if metric_name is not None:
        statement = statement.where(
            MetricNormalized.metric_name == metric_name
        )

    if resource_key is not None:
        statement = statement.where(
            MetricNormalized.resource_key == resource_key
        )

    if cursor is not None:
        last_time, last_id = decode_cursor(cursor, scope)
        statement = statement.where(
            or_(
                MetricNormalized.observed_at > last_time,
                and_(
                    MetricNormalized.observed_at == last_time,
                    MetricNormalized.id > last_id,
                ),
            )
        )

    # Una fila adicional permite saber si existe otra página.
    rows = list(db.scalars(
        statement.order_by(
            MetricNormalized.observed_at,
            MetricNormalized.id,
        ).limit(limit + 1)
    ).all())

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None

    if has_more:
        last = items[-1]
        next_cursor = encode_cursor(last.observed_at, last.id, scope)

    return items, next_cursor