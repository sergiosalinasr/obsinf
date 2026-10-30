"""Selección de resultados para reportes, sin escrituras ni LLM."""

from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisExecution
from app.models.company import Company
from app.models.correlation import Correlation
from app.models.finding import Finding, FindingEvidence, FindingEvent
from app.models.source import Source
from app.models.technology import Technology
from app.schemas.report import ReportRequest


class ReportSelectionError(Exception):
    """Error esperado al seleccionar resultados para un reporte."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def snapshot(row) -> dict:
    """Copia los campos persistidos y normaliza fechas a UTC."""
    result = {}

    for column in row.__table__.columns:
        value = getattr(row, column.key)
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ReportSelectionError(
                    "INVALID_TIMESTAMP", "Fecha sin zona horaria"
                )
            value = value.astimezone(timezone.utc).isoformat()
        result[column.key] = deepcopy(value)

    return result


def _check_execution(execution, request):
    if execution.status not in {"completed", "partial"}:
        raise ReportSelectionError(
            "ANALYSIS_NOT_READY", "Una ejecución no está disponible"
        )

    if not (
        execution.period_start <= request.period_start
        and execution.period_end >= request.period_end
    ):
        raise ReportSelectionError(
            "INCOMPATIBLE_PERIOD",
            "Una ejecución no cubre todo el período solicitado",
        )


def select_report_data(
    db: Session,
    *,
    company_id: int,
    request: ReportRequest,
) -> dict:
    """Selecciona copias independientes, sin confirmar transacciones.

    Se permiten empresas y fuentes desactivadas para consultar históricos.
    La ausencia de resultados no se interpreta como normalidad.
    """
    if type(company_id) is not int or company_id <= 0:
        raise ReportSelectionError(
            "INVALID_COMPANY", "La empresa debe tener un ID positivo"
        )

    with db.no_autoflush:
        company = db.get(Company, company_id)
        if company is None:
            raise ReportSelectionError(
                "COMPANY_NOT_FOUND", "Empresa no encontrada"
            )

        correlations = list(db.scalars(
            select(Correlation)
            .where(
                Correlation.company_id == company_id,
                Correlation.id.in_(request.correlation_ids),
            )
            .order_by(Correlation.id)
        ))

        if {row.id for row in correlations} != set(request.correlation_ids):
            raise ReportSelectionError(
                "CORRELATION_NOT_FOUND",
                "Una correlación no existe en la empresa",
            )

        finding_ids = set(request.finding_ids)
        for row in correlations:
            finding_ids.update([
                row.consumer_finding_id,
                row.provider_finding_id,
            ])

        findings = list(db.scalars(
            select(Finding)
            .where(
                Finding.company_id == company_id,
                Finding.id.in_(finding_ids),
            )
            .order_by(Finding.id)
        ))

        if {row.id for row in findings} != finding_ids:
            raise ReportSelectionError(
                "FINDING_NOT_FOUND",
                "Un hallazgo no existe en la empresa",
            )

        execution_ids = {row.execution_id for row in findings}
        executions = list(db.scalars(
            select(AnalysisExecution)
            .where(
                AnalysisExecution.company_id == company_id,
                AnalysisExecution.id.in_(execution_ids),
            )
            .order_by(AnalysisExecution.id)
        ))

        if {row.id for row in executions} != execution_ids:
            raise ReportSelectionError(
                "ANALYSIS_NOT_FOUND", "Una ejecución no existe en la empresa"
            )

        for execution in executions:
            _check_execution(execution, request)

        for finding in findings:
            if not (
                request.period_start
                <= finding.start_at
                <= finding.end_at
                < request.period_end
            ):
                raise ReportSelectionError(
                    "INCOMPATIBLE_PERIOD",
                    "Un hallazgo queda fuera del período solicitado",
                )

        source_ids = {row.source_id for row in findings}
        source_rows = db.execute(
            select(Source, Technology.code)
            .join(Technology, Source.technology_id == Technology.id)
            .where(
                Source.company_id == company_id,
                Source.id.in_(source_ids),
            )
            .order_by(Source.id)
        ).all()

        if {source.id for source, _ in source_rows} != source_ids:
            raise ReportSelectionError(
                "SOURCE_NOT_FOUND", "Una fuente no existe en la empresa"
            )

        evidence_links = db.execute(
            select(
                FindingEvidence.finding_id,
                FindingEvidence.evidence_id,
            )
            .where(
                FindingEvidence.company_id == company_id,
                FindingEvidence.finding_id.in_(finding_ids),
            )
            .order_by(
                FindingEvidence.finding_id,
                FindingEvidence.evidence_id,
            )
        ).all()

        event_links = db.execute(
            select(FindingEvent.finding_id, FindingEvent.event_id)
            .where(
                FindingEvent.company_id == company_id,
                FindingEvent.finding_id.in_(finding_ids),
            )
            .order_by(FindingEvent.finding_id, FindingEvent.event_id)
        ).all()

        finding_data = {row.id: snapshot(row) for row in findings}
        for item in finding_data.values():
            item["evidence_ids"] = []
            item["event_ids"] = []

        for finding_id, evidence_id in evidence_links:
            finding_data[finding_id]["evidence_ids"].append(evidence_id)

        for finding_id, event_id in event_links:
            finding_data[finding_id]["event_ids"].append(event_id)

        return {
            "schema_version": "report_selection:1.0",
            "company": snapshot(company),
            "request": request.model_dump(mode="json"),
            "sources": [
                {**snapshot(source), "technology": technology}
                for source, technology in source_rows
            ],
            "executions": [snapshot(row) for row in executions],
            "findings": list(finding_data.values()),
            "correlations": [snapshot(row) for row in correlations],
            "scope_note": (
                "Selección explícita de resultados. No constituye un análisis "
                "exhaustivo de toda la infraestructura ni de todos los datos."
            ),
        }