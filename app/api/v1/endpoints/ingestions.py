import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Path,
    Query,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.dependencies import require_local_dev
from app.db.session import get_db
from app.schemas.ingestion import (
    IngestionAccepted,
    IngestionManifest,
)
from app.services.ingestions import (
    IngestionServiceError,
    receive_ingestion,
)

from app.schemas.ingestion import (
    IngestionAccepted,
    IngestionBatchRead,
    IngestionFileRead,
    IngestionManifest,
)
from app.services.ingestions import (
    IngestionServiceError,
    get_ingestion,
    receive_ingestion,
)

from app.schemas.ingestion import (
    IngestionErrorPage,
    IngestionErrorRead,
)
from app.services.ingestions import list_ingestion_errors

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/companies/{company_id}/sources/{source_id}/ingestions",
    tags=["ingestions"],
    dependencies=[Depends(require_local_dev)],
)


@router.post(
    "",
    response_model=IngestionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Fuente no encontrada"},
        409: {"description": "Conflicto de idempotencia o fuente no habilitada"},
        413: {"description": "Límites de carga excedidos"},
        422: {"description": "Manifiesto inválido"},
        503: {"description": "Almacenamiento no disponible"},
    },
)
def post_ingestion(
    company_id: Annotated[int, Path(gt=0)],
    source_id: Annotated[int, Path(gt=0)],
    db: Annotated[Session, Depends(get_db)],
    files: Annotated[list[UploadFile], File()],
    manifest: Annotated[str, Form()],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ],
) -> IngestionAccepted:
    """Recibe archivos y registra un lote para procesamiento posterior."""
    try:
        key = idempotency_key.strip()

        if not key:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_IDEMPOTENCY_KEY"},
            )

        try:
            parsed_manifest = IngestionManifest.model_validate_json(manifest)
        except ValidationError:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_MANIFEST",
                    "message": "El manifiesto no cumple el formato esperado",
                },
            ) from None

        batch = receive_ingestion(
            db,
            company_id,
            source_id,
            key,
            parsed_manifest,
            files,
        )

        return IngestionAccepted(
            batch_id=batch.id,
            status=batch.status,
            status_url=f"/api/v1/companies/{company_id}/ingestions/{batch.id}",
        )

    except IngestionServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from None

    except OSError:
        logger.error("Falló el almacenamiento de una carga")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "STORAGE_UNAVAILABLE",
                "message": "No fue posible conservar los archivos",
            },
        ) from None

    finally:
        # Cerramos los temporales administrados por la recepción multipart.
        for upload in files:
            upload.file.close()

# Las consultas de lotes no requieren conocer previamente su fuente.
query_router = APIRouter(
    prefix="/companies/{company_id}/ingestions",
    tags=["ingestions"],
    dependencies=[Depends(require_local_dev)],
)


@query_router.get(
    "/{batch_id}",
    response_model=IngestionBatchRead,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Lote no encontrado en la empresa"},
    },
)
def get_ingestion_by_id(
    company_id: Annotated[
        int, Path(gt=0, description="Empresa propietaria del lote")
    ],
    batch_id: Annotated[
        int, Path(gt=0, description="Identificador del lote")
    ],
    db: Annotated[Session, Depends(get_db)],
) -> IngestionBatchRead:
    """Consulta el estado, los contadores y los archivos de una carga."""
    try:
        batch, files = get_ingestion(db, company_id, batch_id)
    except IngestionServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from None

    # Excluimos files temporalmente para construirlo desde su consulta.
    data = {
        field: getattr(batch, field)
        for field in IngestionBatchRead.model_fields
        if field != "files"
    }
    data["files"] = [
        IngestionFileRead.model_validate(file)
        for file in files
    ]

    return IngestionBatchRead.model_validate(data)

@query_router.get(
    "/{batch_id}/errors",
    response_model=IngestionErrorPage,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Lote no encontrado en la empresa"},
    },
)
def get_ingestion_errors(
    company_id: Annotated[
        int, Path(gt=0, description="Empresa propietaria del lote")
    ],
    batch_id: Annotated[
        int, Path(gt=0, description="Identificador del lote")
    ],
    db: Annotated[Session, Depends(get_db)],
    after_id: Annotated[
        int, Query(ge=0, description="Último ID recibido; 0 para iniciar")
    ] = 0,
    limit: Annotated[
        int, Query(ge=1, le=1000, description="Cantidad máxima de errores")
    ] = 100,
) -> IngestionErrorPage:
    """Consulta los errores registrados durante el procesamiento."""
    try:
        items, next_after_id = list_ingestion_errors(
            db,
            company_id,
            batch_id,
            after_id=after_id,
            limit=limit,
        )
    except IngestionServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from None

    return IngestionErrorPage(
        items=[
            IngestionErrorRead.model_validate(item)
            for item in items
        ],
        next_after_id=next_after_id,
    )