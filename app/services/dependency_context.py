"""Selección de contexto para interpretar una dependencia.

Este servicio solo consulta y construye una copia serializable.
No ejecuta agentes, no guarda resultados ni confirma transacciones.
"""

from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisExecution, Evidence
from app.models.company import Company
from app.models.finding import Finding, FindingEvidence, FindingEvent
from app.models.resource_dependency import ResourceDependency
from app.models.source import Source
from app.models.technology import Technology


class DependencyContextError(Exception):
    """Error esperado al seleccionar el contexto conjunto."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _iso(value: datetime) -> str:
    """Normaliza instantes para el contrato de salida."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise DependencyContextError(
            "INVALID_TIMESTAMP",
            "El contexto contiene una fecha sin zona horaria",
        )
    return value.astimezone(timezone.utc).isoformat()


def _snapshot(row) -> dict:
    """Copia los campos persistidos sin devolver objetos ORM."""
    return {
        column.key: (
            _iso(value)
            if isinstance(value := getattr(row, column.key), datetime)
            else deepcopy(value)
        )
        for column in row.__table__.columns
    }


def _load_side(
    db: Session,
    *,
    company_id: int,
    finding_id: int,
    source_id: int,
    resource_key: str,
    expected_technology: str,
) -> tuple[dict, AnalysisExecution]:
    """Selecciona un extremo y valida sus referencias de evidencia."""
    source = db.scalar(
        select(Source)
        .join(Technology, Source.technology_id == Technology.id)
        .where(
            Source.company_id == company_id,
            Source.id == source_id,
            Technology.code == expected_technology,
        )
    )

    if source is None:
        raise DependencyContextError(
            "SOURCE_NOT_SUPPORTED",
            "La fuente no corresponde a la tecnología esperada",
        )

    finding = db.scalar(
        select(Finding).where(
            Finding.company_id == company_id,
            Finding.id == finding_id,
            Finding.source_id == source_id,
            Finding.resource_key == resource_key,
        )
    )

    if finding is None:
        raise DependencyContextError(
            "FINDING_NOT_FOUND",
            "Hallazgo no encontrado en el recurso indicado",
        )

    execution = db.scalar(
        select(AnalysisExecution).where(
            AnalysisExecution.company_id == company_id,
            AnalysisExecution.id == finding.execution_id,
        )
    )

    if execution is None or execution.status not in {"completed", "partial"}:
        raise DependencyContextError(
            "ANALYSIS_NOT_READY",
            "La ejecución no está disponible para interpretación",
        )

    if not (
        execution.period_start
        <= finding.start_at
        <= finding.end_at
        < execution.period_end
    ):
        raise DependencyContextError(
            "INVALID_FINDING_PERIOD",
            "El hallazgo está fuera del período de su ejecución",
        )

    evidence_ids = list(
        db.scalars(
            select(FindingEvidence.evidence_id)
            .where(
                FindingEvidence.company_id == company_id,
                FindingEvidence.finding_id == finding.id,
            )
            .order_by(FindingEvidence.evidence_id)
        )
    )

    evidence = list(
        db.scalars(
            select(Evidence)
            .where(
                Evidence.company_id == company_id,
                Evidence.execution_id == execution.id,
                Evidence.source_id == source_id,
                Evidence.resource_key == resource_key,
                Evidence.id.in_(evidence_ids),
            )
            .order_by(Evidence.id)
        )
    )

    if not evidence_ids or {item.id for item in evidence} != set(evidence_ids):
        raise DependencyContextError(
            "INVALID_EVIDENCE",
            "Las evidencias no corresponden al contexto del hallazgo",
        )

    for item in evidence:
        if not (
            finding.start_at <= item.start_at <= item.end_at <= finding.end_at
        ):
            raise DependencyContextError(
                "INVALID_EVIDENCE_PERIOD",
                "Una evidencia está fuera del período del hallazgo",
            )

    event_ids = list(
        db.scalars(
            select(FindingEvent.event_id)
            .where(
                FindingEvent.company_id == company_id,
                FindingEvent.finding_id == finding.id,
            )
            .order_by(FindingEvent.event_id)
        )
    )

    # Conservamos exactamente la selección que recibió el especialista.
    # No incorporamos eventos nuevos al reinterpretar un hallazgo guardado.
    finding_data = _snapshot(finding)
    finding_data["evidence_ids"] = evidence_ids
    finding_data["event_ids"] = event_ids

    return {
        "source": {
            "id": source.id,
            "technology": expected_technology,
            "resource_key": resource_key,
            "is_active": source.is_active,
        },
        "execution": _snapshot(execution),
        "finding": finding_data,
        "evidence": [_snapshot(item) for item in evidence],
    }, execution


def build_dependency_context(
    db: Session,
    *,
    company_id: int,
    dependency_id: int,
    consumer_finding_id: int,
    provider_finding_id: int,
) -> dict:
    """Construye el contexto WebLogic–Oracle de una dependencia activa.

    Permite consultar hallazgos históricos de empresas o fuentes
    desactivadas, pero exige seleccionar una dependencia activa.

    El llamador administra el cierre o rollback de la sesión.
    """
    identifiers = (
        company_id,
        dependency_id,
        consumer_finding_id,
        provider_finding_id,
    )
    if any(type(value) is not int or value <= 0 for value in identifiers):
        raise DependencyContextError(
            "INVALID_ID", "Los identificadores deben ser enteros positivos"
        )

    # Evita que una consulta dispare escrituras pendientes por autoflush.
    with db.no_autoflush:
        if db.get(Company, company_id) is None:
            raise DependencyContextError(
                "COMPANY_NOT_FOUND", "Empresa no encontrada"
            )

        dependency = db.scalar(
            select(ResourceDependency)
            .where(
                ResourceDependency.company_id == company_id,
                ResourceDependency.id == dependency_id,
            )
            .execution_options(populate_existing=True)
        )

        if dependency is None:
            raise DependencyContextError(
                "DEPENDENCY_NOT_FOUND", "Dependencia no encontrada"
            )

        if not dependency.is_active:
            raise DependencyContextError(
                "DEPENDENCY_INACTIVE", "La dependencia está inactiva"
            )

        if dependency.dependency_type != "uses_database_service":
            raise DependencyContextError(
                "DEPENDENCY_NOT_SUPPORTED", "Tipo de dependencia no soportado"
            )

        consumer, consumer_execution = _load_side(
            db,
            company_id=company_id,
            finding_id=consumer_finding_id,
            source_id=dependency.consumer_source_id,
            resource_key=dependency.consumer_resource_key,
            expected_technology="weblogic",
        )
        provider, provider_execution = _load_side(
            db,
            company_id=company_id,
            finding_id=provider_finding_id,
            source_id=dependency.provider_source_id,
            resource_key=dependency.provider_resource_key,
            expected_technology="oracle",
        )

        # Los períodos de análisis son intervalos [inicio, fin).
        overlap_start = max(
            consumer_execution.period_start,
            provider_execution.period_start,
        )
        overlap_end = min(
            consumer_execution.period_end,
            provider_execution.period_end,
        )

        if overlap_start >= overlap_end:
            raise DependencyContextError(
                "NO_COMMON_PERIOD",
                "Las ejecuciones no tienen un período común",
            )

        # Las ventanas de hallazgo incluyen la primera y última muestra.
        # Una muestra puntual también puede coincidir con otra ventana.
        finding_start = max(
            consumer_execution.period_start,
            provider_execution.period_start,
            datetime.fromisoformat(consumer["finding"]["start_at"]),
            datetime.fromisoformat(provider["finding"]["start_at"]),
        )
        finding_end = min(
            datetime.fromisoformat(consumer["finding"]["end_at"]),
            datetime.fromisoformat(provider["finding"]["end_at"]),
        )
        findings_overlap = finding_start <= finding_end

        return {
            "schema_version": "dependency_context:1.0",
            "company_id": company_id,
            "dependency": _snapshot(dependency),
            "consumer": consumer,
            "provider": provider,
            "comparison": {
                "common_period_start": _iso(overlap_start),
                "common_period_end": _iso(overlap_end),
                "same_data_cutoff": (
                    consumer_execution.data_cutoff_at
                    == provider_execution.data_cutoff_at
                ),
                "findings_overlap": findings_overlap,
                "finding_overlap_start": (
                    _iso(finding_start) if findings_overlap else None
                ),
                "finding_overlap_end": (
                    _iso(finding_end) if findings_overlap else None
                ),
            },
            "limitations": [
                "La dependencia es configuración declarada, no prueba causal.",
                "No se ha comprobado su vigencia histórica.",
                "Cada ejecución conserva su propio corte de recepción de datos.",
                "Un solapamiento de ventanas no demuestra continuidad ni causalidad.",
                "Los hallazgos son interpretaciones; las evidencias son su sustento.",
                "El contexto de eventos conserva la selección original del especialista.",
                "Las métricas JDBC no identifican por sí solas un datasource específico.",
            ],
        }