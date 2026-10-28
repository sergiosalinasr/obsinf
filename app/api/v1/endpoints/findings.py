"""Consulta de hallazgos almacenados, protegida por el modo local actual."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_local_dev
from app.db.session import get_db
from app.schemas.finding import (
    FindingClassification,
    FindingPage,
    FindingRead,
    FindingSeverity,
)
from app.services.finding_queries import FindingQueryError, get_finding, list_findings


MAX_ID = 9223372036854775807


router = APIRouter(
    prefix="/companies/{company_id}/findings",
    tags=["findings"],
    dependencies=[Depends(require_local_dev)],
)


def _not_found(error: FindingQueryError) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": error.code, "message": error.message},
    )


@router.get(
    "",
    response_model=FindingPage,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa no encontrada"},
        422: {"description": "Filtros o paginación inválidos"},
    },
)
def get_findings(
    company_id: Annotated[int, Path(gt=0, le=MAX_ID)],
    db: Annotated[Session, Depends(get_db)],
    execution_id: Annotated[int | None, Query(gt=0, le=MAX_ID)] = None,
    source_id: Annotated[int | None, Query(gt=0, le=MAX_ID)] = None,
    resource_key: Annotated[str | None, Query(min_length=1, max_length=500)] = None,
    classification: FindingClassification | None = None,
    severity: FindingSeverity | None = None,
    after_id: Annotated[
        int, Query(ge=0, le=MAX_ID, description="Último ID recibido; 0 para iniciar")
    ] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> FindingPage:
    """Lista hallazgos por ID ascendente con filtros de coincidencia exacta.

    Conservar los filtros al enviar next_after_id como after_id.
    Consultar hallazgos no ejecuta el agente ni genera nuevas interpretaciones.
    """
    try:
        items, next_after_id = list_findings(
            db,
            company_id=company_id,
            execution_id=execution_id,
            source_id=source_id,
            resource_key=resource_key,
            classification=classification,
            severity=severity,
            after_id=after_id,
            limit=limit,
        )
    except FindingQueryError as error:
        raise _not_found(error) from None
    return FindingPage(items=items, next_after_id=next_after_id)


@router.get(
    "/{finding_id}",
    response_model=FindingRead,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Hallazgo no encontrado en la empresa"},
    },
)
def get_finding_detail(
    company_id: Annotated[int, Path(gt=0, le=MAX_ID)],
    finding_id: Annotated[int, Path(gt=0, le=MAX_ID)],
    db: Annotated[Session, Depends(get_db)],
) -> FindingRead:
    """Consulta un hallazgo, su procedencia y los IDs de sus evidencias."""
    try:
        return get_finding(db, company_id, finding_id)
    except FindingQueryError as error:
        raise _not_found(error) from None
