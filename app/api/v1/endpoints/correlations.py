"""Consultas HTTP de correlaciones guardadas."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_local_dev
from app.db.session import get_db
from app.schemas.correlation import CorrelationDetail, CorrelationRead
from app.services.correlation_queries import (
    CorrelationQueryError,
    get_correlation,
    list_correlations,
)


router = APIRouter(
    prefix="/companies/{company_id}/correlations",
    tags=["correlations"],
    dependencies=[Depends(require_local_dev)],
)

CompanyId = Annotated[int, Path(gt=0, description="Empresa propietaria")]
Database = Annotated[Session, Depends(get_db)]


@router.get(
    "",
    response_model=list[CorrelationRead],
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa no encontrada"},
        422: {"description": "Filtros o paginación inválidos"},
    },
)
def get_company_correlations(
    company_id: CompanyId,
    db: Database,
    dependency_id: Annotated[
        int | None, Query(gt=0, description="Dependencia configurada")
    ] = None,
    after_id: Annotated[
        int, Query(ge=0, description="Último ID recibido; 0 para iniciar")
    ] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[CorrelationRead]:
    """Lista correlaciones sin incluir el contexto completo."""
    try:
        rows = list_correlations(
            db,
            company_id,
            dependency_id=dependency_id,
            after_id=after_id,
            limit=limit,
        )
    except CorrelationQueryError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from None

    return [CorrelationRead.model_validate(row) for row in rows]


@router.get(
    "/{correlation_id}",
    response_model=CorrelationDetail,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa o correlación no encontrada"},
    },
)
def get_correlation_detail(
    company_id: CompanyId,
    correlation_id: Annotated[
        int, Path(gt=0, description="Identificador de la correlación")
    ],
    db: Database,
) -> CorrelationDetail:
    """Recupera el resultado y su contexto histórico."""
    try:
        row = get_correlation(db, company_id, correlation_id)
    except CorrelationQueryError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from None

    return CorrelationDetail.model_validate(row)