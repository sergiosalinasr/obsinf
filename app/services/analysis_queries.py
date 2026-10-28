from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisExecution, Evidence, EvidenceMetric
from app.schemas.analysis import EvidenceRead


class AnalysisQueryError(Exception):
    """Error esperado al consultar una ejecución."""


def get_execution(
    db: Session,
    company_id: int,
    execution_id: int,
) -> AnalysisExecution:
    """Obtiene una ejecución solo si pertenece a la empresa indicada."""
    execution = db.scalar(
        select(AnalysisExecution).where(
            AnalysisExecution.company_id == company_id,
            AnalysisExecution.id == execution_id,
        )
    )

    if execution is None:
        raise AnalysisQueryError("Ejecución de análisis no encontrada")

    return execution


def list_evidence(
    db: Session,
    company_id: int,
    execution_id: int,
    after_id: int = 0,
    limit: int = 100,
) -> tuple[list[EvidenceRead], int | None]:
    """Lista evidencias y sus métricas dentro de la ejecución solicitada."""
    get_execution(db, company_id, execution_id)

    rows = list(
        db.scalars(
            select(Evidence)
            .where(
                Evidence.company_id == company_id,
                Evidence.execution_id == execution_id,
                Evidence.id > after_id,
            )
            .order_by(Evidence.id)
            .limit(limit + 1)
        ).all()
    )

    items = rows[:limit]
    next_after_id = items[-1].id if len(rows) > limit else None

    # Recuperamos las asociaciones de toda la página en una consulta.
    metric_ids_by_evidence = {item.id: [] for item in items}

    if items:
        associations = db.execute(
            select(
                EvidenceMetric.evidence_id,
                EvidenceMetric.metric_id,
            )
            .where(
                EvidenceMetric.company_id == company_id,
                EvidenceMetric.evidence_id.in_(
                    [item.id for item in items]
                ),
            )
            .order_by(
                EvidenceMetric.evidence_id,
                EvidenceMetric.metric_id,
            )
        ).all()

        for evidence_id, metric_id in associations:
            metric_ids_by_evidence[evidence_id].append(metric_id)

    result = []

    for item in items:
        result.append(EvidenceRead(
            id=item.id,
            company_id=item.company_id,
            execution_id=item.execution_id,
            rule_id=item.rule_id,
            source_id=item.source_id,
            evidence_type=item.evidence_type,
            resource_key=item.resource_key,
            metric_name=item.metric_name,
            unit=item.unit,
            series_key=item.series_key,
            comparison=item.comparison,
            threshold_value=item.threshold_value,
            min_observed=item.min_observed,
            max_observed=item.max_observed,
            start_at=item.start_at,
            end_at=item.end_at,
            duration_seconds=item.duration_seconds,
            sample_count=item.sample_count,
            created_at=item.created_at,
            metric_ids=metric_ids_by_evidence[item.id],
        ))

    return result, next_after_id