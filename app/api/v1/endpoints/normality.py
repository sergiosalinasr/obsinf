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
from app.schemas.normality import (
    ProfileCreate,
    ProfileDetail,
    ProfileRead,
    RuleCreate,
    RuleRead,
)
from app.services.normality import (
    NormalityError,
    activate_profile,
    create_profile,
    create_rule,
    get_profile,
    list_profiles,
)


router = APIRouter(
    prefix="/companies/{company_id}/normality-profiles",
    tags=["normality"],
    dependencies=[Depends(require_local_dev)],
)


def http_error(exc: NormalityError) -> HTTPException:
    """Traduce errores esperados del servicio a respuestas de la API."""
    not_found = {
        "COMPANY_NOT_FOUND",
        "PROFILE_NOT_FOUND",
        "SOURCE_NOT_FOUND",
    }
    invalid = {
        "INVALID_DIMENSIONS",
        "DIMENSIONS_NOT_SUPPORTED",
    }

    if exc.code in not_found:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in invalid:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        code = status.HTTP_409_CONFLICT

    return HTTPException(
        status_code=code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post(
    "",
    response_model=ProfileRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa no encontrada"},
        409: {"description": "Empresa inactiva o versión duplicada"},
    },
)
def post_profile(
    company_id: Annotated[int, Path(gt=0)],
    payload: ProfileCreate,
    db: Annotated[Session, Depends(get_db)],
) -> ProfileRead:
    """Crea una versión de perfil en borrador."""
    try:
        profile = create_profile(db, company_id, payload)
    except NormalityError as exc:
        raise http_error(exc) from None

    return ProfileRead.model_validate(profile)


@router.get(
    "",
    response_model=list[ProfileRead],
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa no encontrada"},
    },
)
def get_profiles(
    company_id: Annotated[int, Path(gt=0)],
    db: Annotated[Session, Depends(get_db)],
    after_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[ProfileRead]:
    """Lista perfiles activos, borradores e históricos de la empresa."""
    try:
        profiles = list_profiles(db, company_id, after_id, limit)
    except NormalityError as exc:
        raise http_error(exc) from None

    return [ProfileRead.model_validate(item) for item in profiles]


@router.get(
    "/{profile_id}",
    response_model=ProfileDetail,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Perfil no encontrado en la empresa"},
    },
)
def get_profile_by_id(
    company_id: Annotated[int, Path(gt=0)],
    profile_id: Annotated[int, Path(gt=0)],
    db: Annotated[Session, Depends(get_db)],
) -> ProfileDetail:
    """Consulta una versión y sus reglas."""
    try:
        profile, rules = get_profile(db, company_id, profile_id)
    except NormalityError as exc:
        raise http_error(exc) from None

    # Creamos primero la representación base desde el modelo SQLAlchemy.
    data = ProfileRead.model_validate(profile).model_dump()
    data["rules"] = [RuleRead.model_validate(rule) for rule in rules]

    return ProfileDetail.model_validate(data)


@router.post(
    "/{profile_id}/rules",
    response_model=RuleRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Perfil o fuente no encontrada"},
        409: {"description": "Perfil no editable o regla duplicada"},
        422: {"description": "Regla o dimensiones inválidas"},
    },
)
def post_rule(
    company_id: Annotated[int, Path(gt=0)],
    profile_id: Annotated[int, Path(gt=0)],
    payload: RuleCreate,
    db: Annotated[Session, Depends(get_db)],
) -> RuleRead:
    """Agrega una regla a un perfil en borrador."""
    try:
        rule = create_rule(db, company_id, profile_id, payload)
    except NormalityError as exc:
        raise http_error(exc) from None

    return RuleRead.model_validate(rule)


@router.post(
    "/{profile_id}/activate",
    response_model=ProfileRead,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Perfil no encontrado"},
        409: {"description": "El perfil no puede activarse"},
    },
)
def post_activate_profile(
    company_id: Annotated[int, Path(gt=0)],
    profile_id: Annotated[int, Path(gt=0)],
    db: Annotated[Session, Depends(get_db)],
) -> ProfileRead:
    """Activa el borrador y retira la versión activa anterior."""
    try:
        profile = activate_profile(db, company_id, profile_id)
    except NormalityError as exc:
        raise http_error(exc) from None

    return ProfileRead.model_validate(profile)