"""API de dependencias explícitas entre recursos de una empresa."""

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    status,
)
from sqlalchemy.orm import Session

from app.api.dependencies import require_local_dev
from app.db.session import get_db
from app.schemas.resource_dependency import (
    DependencyCreate,
    DependencyRead,
    DependencyUpdate,
)
from app.services.resource_dependencies import (
    DependencyError,
    create_dependency,
    get_dependency,
    list_dependencies,
    set_dependency_active,
)


router = APIRouter(
    prefix="/companies/{company_id}/dependencies",
    tags=["dependencies"],
    dependencies=[Depends(require_local_dev)],
)

CompanyId = Annotated[
    int, Path(gt=0, description="Empresa propietaria")
]
DependencyId = Annotated[
    int, Path(gt=0, description="Identificador de la dependencia")
]
Database = Annotated[Session, Depends(get_db)]

ERROR_RESPONSES = {
    403: {"description": "Acceso no habilitado"},
    404: {"description": "Empresa, fuente o dependencia no encontrada"},
    409: {"description": "Relación duplicada o entidad inactiva"},
    422: {"description": "Solicitud o relación inválida"},
}


def business_error(exc: DependencyError) -> HTTPException:
    """Conserva el formato de errores utilizado por OBSINF."""
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post(
    "",
    response_model=DependencyRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def post_dependency(
    company_id: CompanyId,
    payload: DependencyCreate,
    db: Database,
) -> DependencyRead:
    """Registra una relación configurada; no infiere causalidad."""
    try:
        dependency = create_dependency(
            db,
            company_id,
            payload,
            # Identidad del contexto local, nunca tomada del body.
            configured_by="local-dev",
        )
    except DependencyError as exc:
        raise business_error(exc) from None

    return DependencyRead.model_validate(dependency)


@router.get(
    "",
    response_model=list[DependencyRead],
    responses=ERROR_RESPONSES,
)
def get_company_dependencies(
    company_id: CompanyId,
    db: Database,
    is_active: Annotated[
        bool | None,
        Query(description="Omitir para consultar ambos estados"),
    ] = None,
    after_id: Annotated[
        int,
        Query(ge=0, description="Último ID recibido; 0 para iniciar"),
    ] = 0,
    limit: Annotated[
        int, Query(ge=1, le=1000, description="Cantidad máxima")
    ] = 100,
) -> list[DependencyRead]:
    """Lista relaciones de la empresa por ID ascendente."""
    try:
        dependencies = list_dependencies(
            db,
            company_id,
            is_active=is_active,
            after_id=after_id,
            limit=limit,
        )
    except DependencyError as exc:
        raise business_error(exc) from None

    return [
        DependencyRead.model_validate(item)
        for item in dependencies
    ]


@router.get(
    "/{dependency_id}",
    response_model=DependencyRead,
    responses=ERROR_RESPONSES,
)
def get_dependency_detail(
    company_id: CompanyId,
    dependency_id: DependencyId,
    db: Database,
) -> DependencyRead:
    """Consulta una relación sin exponer registros de otra empresa."""
    try:
        dependency = get_dependency(
            db, company_id, dependency_id
        )
    except DependencyError as exc:
        raise business_error(exc) from None

    return DependencyRead.model_validate(dependency)


@router.patch(
    "/{dependency_id}",
    response_model=DependencyRead,
    responses=ERROR_RESPONSES,
)
def patch_dependency(
    company_id: CompanyId,
    dependency_id: DependencyId,
    payload: DependencyUpdate,
    db: Database,
) -> DependencyRead:
    """Activa o desactiva conservando la identidad de la relación."""
    try:
        dependency = set_dependency_active(
            db,
            company_id,
            dependency_id,
            is_active=payload.is_active,
        )
    except DependencyError as exc:
        raise business_error(exc) from None

    return DependencyRead.model_validate(dependency)