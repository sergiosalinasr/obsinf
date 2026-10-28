import logging
from tempfile import TemporaryFile

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.api.v1.endpoints.companies import router as companies_router

from app.core.config import get_settings
from app.db.session import engine
from app.api.v1.endpoints.technologies import router as technologies_router
from app.api.v1.endpoints.sources import router as sources_router

from app.api.v1.endpoints.ingestions import router as ingestions_router
from app.api.v1.endpoints.ingestions import (
    query_router as ingestion_query_router,
)

from app.api.v1.endpoints.metrics import router as metrics_router
from app.api.v1.endpoints.events import router as events_router
from app.api.v1.endpoints.normality import router as normality_router
from app.api.v1.endpoints.analyses import router as analyses_router
from app.api.v1.endpoints.findings import router as findings_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="OBSINF",
    description="Plataforma multiempresa de observabilidad inteligente",
    version="0.1.0",
)

app.include_router(companies_router, prefix="/api/v1")
app.include_router(technologies_router, prefix="/api/v1")
app.include_router(sources_router, prefix="/api/v1")
app.include_router(ingestions_router, prefix="/api/v1")
app.include_router(ingestion_query_router, prefix="/api/v1")
app.include_router(metrics_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")
app.include_router(normality_router, prefix="/api/v1")
app.include_router(analyses_router, prefix="/api/v1")
app.include_router(findings_router, prefix="/api/v1")

@app.get("/api/v1/health/live", tags=["health"])
def health_live() -> dict[str, str]:
    return {"status": "ok", "application": "obsinf"}


@app.get("/api/v1/health/ready", tags=["health"])
def health_ready() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.error("Falló la comprobación de PostgreSQL")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DATABASE_UNAVAILABLE",
                "message": "Base de datos no disponible",
            },
        ) from None

    try:
        data_dir = get_settings().data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        with TemporaryFile(dir=data_dir) as probe:
            probe.write(b"obsinf")
            probe.flush()
            probe.seek(0)

            if probe.read() != b"obsinf":
                raise OSError("Falló la verificación del almacenamiento")

    except OSError:
        logger.error("Falló la comprobación del almacenamiento")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "STORAGE_UNAVAILABLE",
                "message": "Almacenamiento no disponible",
            },
        ) from None

    return {
        "status": "ready",
        "database": "ok",
        "storage": "ok",
    }