"""Listado, detalle y descarga de reportes conservados."""

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Response,
)
from sqlalchemy.orm import Session

from app.api.dependencies import require_local_dev
from app.db.session import get_db
from app.schemas.report_queries import ReportDetail, ReportRead
from app.services.report_queries import (
    ReportQueryError,
    get_report,
    list_reports,
)


router = APIRouter(
    prefix="/companies/{company_id}/reports",
    tags=["reports"],
    dependencies=[Depends(require_local_dev)],
)

CompanyId = Annotated[
    int, Path(gt=0, description="Empresa propietaria")
]
ReportId = Annotated[
    int, Path(gt=0, description="Identificador del reporte")
]
Database = Annotated[Session, Depends(get_db)]


def query_error(exc: ReportQueryError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.get(
    "",
    response_model=list[ReportRead],
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa no encontrada"},
        422: {"description": "Paginación inválida"},
    },
)
def get_company_reports(
    company_id: CompanyId,
    db: Database,
    after_id: Annotated[
        int, Query(ge=0, description="Último ID recibido; 0 para iniciar")
    ] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[ReportRead]:
    """Lista metadatos sin incluir el contenido completo."""
    try:
        rows = list_reports(
            db,
            company_id,
            after_id=after_id,
            limit=limit,
        )
    except ReportQueryError as exc:
        raise query_error(exc) from None

    return [ReportRead.model_validate(row) for row in rows]


@router.get(
    "/{report_id}",
    response_model=ReportDetail,
    responses={
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa o reporte no encontrado"},
    },
)
def get_report_detail(
    company_id: CompanyId,
    report_id: ReportId,
    db: Database,
) -> ReportDetail:
    """Recupera el Markdown guardado, sin regenerarlo."""
    try:
        report = get_report(db, company_id, report_id)
    except ReportQueryError as exc:
        raise query_error(exc) from None

    return ReportDetail.model_validate(report)


@router.get(
    "/{report_id}/markdown",
    response_class=Response,
    responses={
        200: {
            "description": "Archivo Markdown conservado",
            "content": {
                "text/markdown": {
                    "schema": {"type": "string"}
                }
            },
        },
        403: {"description": "Acceso no habilitado"},
        404: {"description": "Empresa o reporte no encontrado"},
    },
)
def download_report_markdown(
    company_id: CompanyId,
    report_id: ReportId,
    db: Database,
) -> Response:
    """Descarga exactamente el contenido almacenado en UTF-8."""
    try:
        report = get_report(db, company_id, report_id)
    except ReportQueryError as exc:
        raise query_error(exc) from None

    filename = f"obsinf_company_{company_id}_report_{report_id}.md"

    return Response(
        content=report.content_markdown.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )