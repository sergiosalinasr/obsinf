from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_local_dev
from app.db.session import get_db
from app.schemas.source import SourceCreate, SourceRead
from app.services.sources import (
    SourceRegistrationError,
    create_source,
    get_source,
    list_sources,
)
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

router = APIRouter(
    prefix="/companies/{company_id}/sources",
    tags=["sources"],
    dependencies=[Depends(require_local_dev)],
)


@router.post(
    "",
    response_model=SourceRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa o tecnología no encontrada"},
        409: {
            "description": (
                "Código duplicado, entidad inactiva "
                "o tecnología no soportada"
            )
        },
    },
)
def post_source(
    company_id: Annotated[
        int,
        Path(gt=0, description="Empresa propietaria de la fuente"),
    ],
    payload: SourceCreate,
    db: Annotated[Session, Depends(get_db)],
) -> SourceRead:
    """Registra una fuente asociada a la empresa indicada."""
    try:
        source = create_source(db, company_id, payload)
    except SourceRegistrationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        ) from None

    return SourceRead.model_validate(source)

@router.get(
    "",
    response_model=list[SourceRead],
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa no encontrada"},
    },
)
def get_company_sources(
    company_id: Annotated[
        int, Path(gt=0, description="Empresa propietaria")
    ],
    db: Annotated[Session, Depends(get_db)],
    after_id: Annotated[
        int, Query(ge=0, description="Último ID recibido; 0 para iniciar")
    ] = 0,
    limit: Annotated[
        int, Query(ge=1, le=1000, description="Cantidad máxima de fuentes")
    ] = 100,
) -> list[SourceRead]:
    """Lista fuentes de la empresa con paginación por ID."""
    try:
        sources = list_sources(
            db,
            company_id,
            after_id=after_id,
            limit=limit,
        )
    except SourceRegistrationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from None

    return [SourceRead.model_validate(source) for source in sources]


@router.get(
    "/{source_id}",
    response_model=SourceRead,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa o fuente no encontrada"},
    },
)
def get_company_source(
    company_id: Annotated[
        int, Path(gt=0, description="Empresa propietaria")
    ],
    source_id: Annotated[
        int, Path(gt=0, description="Identificador de la fuente")
    ],
    db: Annotated[Session, Depends(get_db)],
) -> SourceRead:
    """Consulta una fuente sin permitir cruces entre empresas."""
    try:
        source = get_source(db, company_id, source_id)
    except SourceRegistrationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from None

    return SourceRead.model_validate(source)