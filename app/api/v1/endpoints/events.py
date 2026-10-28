from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.api.dependencies import require_local_dev
from app.db.session import get_db
from app.schemas.event import EventPage, EventRead
from app.services.events import EventQueryError, query_events


router = APIRouter(
    prefix="/companies/{company_id}/events",
    tags=["events"],
    dependencies=[Depends(require_local_dev)],
)


@router.get(
    "",
    response_model=EventPage,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa o fuente no encontrada"},
        422: {"description": "Período, filtros o cursor inválidos"},
    },
)
def get_events(
    company_id: Annotated[int, Path(gt=0)],
    db: Annotated[Session, Depends(get_db)],
    period_start: Annotated[
        AwareDatetime,
        Query(alias="from", description="Inicio inclusivo con zona horaria"),
    ],
    period_end: Annotated[
        AwareDatetime,
        Query(alias="to", description="Fin exclusivo con zona horaria"),
    ],
    source_id: Annotated[int | None, Query(gt=0)] = None,
    severity: Annotated[
        Literal[
            "unknown", "debug", "info", "warning", "error", "critical"
        ] | None,
        Query(),
    ] = None,
    event_code: Annotated[
        str | None, Query(min_length=1, max_length=200)
    ] = None,
    resource_key: Annotated[
        str | None, Query(min_length=1, max_length=500)
    ] = None,
    record_type: Annotated[
        Literal["event", "log"] | None, Query()
    ] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    cursor: Annotated[
        str | None, Query(min_length=1, max_length=2048)
    ] = None,
) -> EventPage:
    """Consulta eventos y logs normalizados de una empresa."""
    try:
        items, next_cursor = query_events(
            db=db,
            company_id=company_id,
            period_start=period_start,
            period_end=period_end,
            source_id=source_id,
            severity=severity,
            event_code=event_code,
            resource_key=resource_key,
            record_type=record_type,
            limit=limit,
            cursor=cursor,
        )
    except EventQueryError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from None

    return EventPage(
        items=[EventRead.model_validate(item) for item in items],
        next_cursor=next_cursor,
    )