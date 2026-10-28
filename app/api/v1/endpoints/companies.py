from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.company import CompanyCreate, CompanyRead, CompanyUpdate
from app.services.companies import (
    CompanyCodeAlreadyExists,
    create_company,
    get_company,
    list_companies,
    update_company,
)

from app.api.dependencies import require_local_dev


router = APIRouter(
    prefix="/companies",
    tags=["companies"],
    dependencies=[Depends(require_local_dev)],
)


@router.post(
    "",
    response_model=CompanyRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"description": "Acceso no habilitado"},
        409: {"description": "Ya existe una empresa con ese código"},
    },
)
def post_company(
    payload: CompanyCreate,
    db: Annotated[Session, Depends(get_db)],
) -> CompanyRead:
    try:
        company = create_company(db, payload)
    except CompanyCodeAlreadyExists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "COMPANY_CODE_EXISTS",
                "message": "Ya existe una empresa con ese código",
            },
        ) from None

    return CompanyRead.model_validate(company)

@router.get(
    "",
    response_model=list[CompanyRead],
    responses={
        403: {"description": "Acceso no habilitado"},
    },
)
def get_companies(
    db: Annotated[Session, Depends(get_db)],
    after_id: Annotated[
        int,
        Query(ge=0, description="Último ID recibido; 0 para iniciar"),
    ] = 0,
    limit: Annotated[
        int,
        Query(ge=1, le=1000, description="Cantidad máxima de empresas"),
    ] = 100,
) -> list[CompanyRead]:
    """Lista empresas en el entorno local de desarrollo."""
    companies = list_companies(db, after_id=after_id, limit=limit)

    return [
        CompanyRead.model_validate(company)
        for company in companies
    ]


@router.get(
    "/{company_id}",
    response_model=CompanyRead,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa no encontrada"},
    },
)
def get_company_by_id(
    company_id: Annotated[
        int,
        Path(gt=0, description="Identificador numérico de la empresa"),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> CompanyRead:
    """Consulta una empresa y devuelve 404 si no existe."""
    company = get_company(db, company_id)

    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "COMPANY_NOT_FOUND",
                "message": "Empresa no encontrada",
            },
        )

    return CompanyRead.model_validate(company)

@router.patch(
    "/{company_id}",
    response_model=CompanyRead,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa no encontrada"},
    },
)
def patch_company(
    company_id: Annotated[
        int,
        Path(gt=0, description="Identificador numérico de la empresa"),
    ],
    payload: CompanyUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> CompanyRead:
    """Modifica nombre, zona horaria o estado de una empresa."""
    company = update_company(db, company_id, payload)

    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "COMPANY_NOT_FOUND",
                "message": "Empresa no encontrada",
            },
        )

    return CompanyRead.model_validate(company)