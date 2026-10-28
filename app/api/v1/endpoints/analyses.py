from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_local_dev
from app.db.session import get_db
from app.schemas.analysis import AnalysisExecutionRead, EvidencePage
from app.services.analysis_queries import (
    AnalysisQueryError,
    get_execution,
    list_evidence,
)


router = APIRouter(
    prefix="/companies/{company_id}/analyses",
    tags=["analyses"],
    dependencies=[Depends(require_local_dev)],
)


def execution_not_found() -> HTTPException:
    """Devuelve la misma respuesta para ejecuciones inexistentes o ajenas."""
    return HTTPException(
        status_code=404,
        detail={
            "code": "ANALYSIS_NOT_FOUND",
            "message": "Ejecución de análisis no encontrada",
        },
    )


@router.get(
    "/{execution_id}",
    response_model=AnalysisExecutionRead,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Ejecución no encontrada en la empresa"},
    },
)
def get_analysis(
    company_id: Annotated[int, Path(gt=0)],
    execution_id: Annotated[int, Path(gt=0)],
    db: Annotated[Session, Depends(get_db)],
) -> AnalysisExecutionRead:
    """Consulta el estado y la cobertura de una ejecución."""
    try:
        execution = get_execution(db, company_id, execution_id)
    except AnalysisQueryError:
        raise execution_not_found() from None

    return AnalysisExecutionRead.model_validate(execution)


@router.get(
    "/{execution_id}/evidence",
    response_model=EvidencePage,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Ejecución no encontrada en la empresa"},
    },
)
def get_analysis_evidence(
    company_id: Annotated[int, Path(gt=0)],
    execution_id: Annotated[int, Path(gt=0)],
    db: Annotated[Session, Depends(get_db)],
    after_id: Annotated[
        int, Query(ge=0, description="Último ID recibido; 0 para iniciar")
    ] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> EvidencePage:
    """Consulta evidencias y los IDs de sus mediciones."""
    try:
        items, next_after_id = list_evidence(
            db,
            company_id=company_id,
            execution_id=execution_id,
            after_id=after_id,
            limit=limit,
        )
    except AnalysisQueryError:
        raise execution_not_found() from None

    return EvidencePage(items=items, next_after_id=next_after_id)