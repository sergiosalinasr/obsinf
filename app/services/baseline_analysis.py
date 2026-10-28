from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.baseline_deviation import (
    BaselineRule,
    MetricPoint,
    detect_baseline_deviations,
)
from app.models.normality import NormalityProfile, NormalityRule
from app.models.observations import MetricNormalized

from app.models.analysis import AnalysisExecution, Evidence, EvidenceMetric

class BaselineAnalysisError(Exception):
    """Error esperado al seleccionar el perfil o analizar sus datos."""


def analyze_profile(
    db: Session,
    company_id: int,
    profile_id: int,
    period_start: datetime,
    period_end: datetime,
    data_cutoff_at: datetime | None = None,
) -> dict:
    """Analiza métricas del período [inicio, fin) para un perfil activo.

    La consulta utiliza empresa y fuente; no depende del lote de ingesta.
    Esta versión devuelve resultados en memoria y no los persiste.
    """
    if (
        period_start.tzinfo is None
        or period_start.utcoffset() is None
        or period_end.tzinfo is None
        or period_end.utcoffset() is None
    ):
        raise BaselineAnalysisError("Las fechas requieren zona horaria")

    start = period_start.astimezone(timezone.utc)
    end = period_end.astimezone(timezone.utc)

    if data_cutoff_at is not None:
        if (
            data_cutoff_at.tzinfo is None
            or data_cutoff_at.utcoffset() is None
        ):
            raise BaselineAnalysisError(
                "La fecha de corte requiere zona horaria"
            )

        data_cutoff_at = data_cutoff_at.astimezone(timezone.utc)

    if start >= end:
        raise BaselineAnalysisError("El inicio debe ser anterior al fin")

    profile = db.scalar(
        select(NormalityProfile).where(
            NormalityProfile.company_id == company_id,
            NormalityProfile.id == profile_id,
        )
    )

    if profile is None:
        raise BaselineAnalysisError(
            "Perfil no encontrado en la empresa"
        )

    if profile.status != "active":
        raise BaselineAnalysisError(
            "El perfil debe estar activo para iniciar un análisis"
        )

    rules = list(
        db.scalars(
            select(NormalityRule)
            .where(
                NormalityRule.company_id == company_id,
                NormalityRule.profile_id == profile_id,
            )
            .order_by(NormalityRule.id)
        ).all()
    )

    if not rules:
        raise BaselineAnalysisError(
            "El perfil no tiene reglas configuradas"
        )

    coverage = []
    evidence = []

    for rule in rules:
        # Los adaptadores todavía no definen qué atributos identifican
        # dimensiones de una serie. Analizamos únicamente la serie vacía.
        if rule.dimensions != {} or rule.series_key != "{}":
            coverage.append({
                "rule_id": rule.id,
                "status": "unsupported_dimensions",
                "samples": 0,
                "excluded_samples": None,
                "evidence_count": 0,
            })
            continue

        measurements = list(
            db.scalars(
                select(MetricNormalized)
                .where(
                    MetricNormalized.company_id == company_id,
                    MetricNormalized.source_id == rule.source_id,
                    MetricNormalized.resource_key == rule.resource_key,
                    MetricNormalized.metric_name == rule.metric_name,
                    MetricNormalized.unit == rule.unit,
                    MetricNormalized.observed_at >= start,
                    MetricNormalized.observed_at < end,
                    # Cuando existe corte, excluye datos recibidos después.
                    *(
                        [MetricNormalized.received_at <= data_cutoff_at]
                        if data_cutoff_at is not None
                        else []
                    ),
                )
                .order_by(
                    MetricNormalized.observed_at,
                    MetricNormalized.id,
                )
            ).all()
        )

        # Hasta definir las dimensiones por adaptador, no mezclamos
        # mediciones con atributos desconocidos en la serie vacía.
        compatible = [item for item in measurements if item.attributes == {}]
        excluded = len(measurements) - len(compatible)

        if not compatible:
            coverage.append({
                "rule_id": rule.id,
                "status": "no_compatible_data",
                "samples": 0,
                "excluded_samples": excluded,
                "evidence_count": 0,
            })
            continue

        detector_rule = BaselineRule(
            company_id=company_id,
            source_id=rule.source_id,
            resource_key=rule.resource_key,
            metric_name=rule.metric_name,
            unit=rule.unit,
            profile_code=profile.code,
            profile_version=profile.version,
            series_key=rule.series_key,
            lower_threshold=rule.lower_threshold,
            upper_threshold=rule.upper_threshold,
            min_samples=rule.min_samples,
            max_gap_seconds=rule.max_gap_seconds,
        )

        points = [
            MetricPoint(
                metric_id=item.id,
                observed_at=item.observed_at,
                value=item.value,
            )
            for item in compatible
        ]

        try:
            deviations = detect_baseline_deviations(points, detector_rule)
        except ValueError as exc:
            # Una serie ambigua no debe presentarse como normal.
            coverage.append({
                "rule_id": rule.id,
                "status": "analysis_error",
                "samples": len(compatible),
                "excluded_samples": excluded,
                "evidence_count": 0,
                "message": str(exc),
            })
            continue

        for item in deviations:
            evidence.append({
                "rule_id": rule.id,
                "evidence_type": item.evidence_type,
                "detector_version": item.detector_version,
                "source_id": item.source_id,
                "resource_key": item.resource_key,
                "metric_name": item.metric_name,
                "unit": item.unit,
                "series_key": item.series_key,
                "comparison": item.comparison,
                "threshold_value": item.threshold_value,
                "start": item.start.isoformat(),
                "end": item.end.isoformat(),
                "duration_seconds": item.duration_seconds,
                "sample_count": item.sample_count,
                "min_observed": item.min_observed,
                "max_observed": item.max_observed,
                "metric_ids": list(item.metric_ids),
            })

        coverage.append({
            "rule_id": rule.id,
            "status": "partial" if excluded else "analyzed",
            "samples": len(compatible),
            "excluded_samples": excluded,
            "evidence_count": len(deviations),
        })

    return {
        "company_id": company_id,
        "profile": {
            "id": profile.id,
            "code": profile.code,
            "version": profile.version,
        },
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "coverage": coverage,
        "evidence": evidence,
    }

def run_and_save_analysis(
    db: Session,
    company_id: int,
    profile_id: int,
    period_start: datetime,
    period_end: datetime,
) -> dict:
    """Analiza y guarda ejecución, evidencias y referencias atómicamente.

    El servicio gestiona commit y rollback de la sesión recibida.
    La versión del perfil y la cobertura quedan registradas.
    """
    from app.analysis.baseline_deviation import DETECTOR_VERSION

    try:
        started_at = db.scalar(select(func.clock_timestamp()))

        # La fecha de corte se toma del reloj PostgreSQL.
        data_cutoff_at = db.scalar(select(func.clock_timestamp()))

        result = analyze_profile(
            db=db,
            company_id=company_id,
            profile_id=profile_id,
            period_start=period_start,
            period_end=period_end,
            data_cutoff_at=data_cutoff_at,
        )

        # El perfil debe seguir activo al momento de registrar el resultado.
        # Este bloqueo también serializa con la activación de otra versión.
        profile = db.scalar(
            select(NormalityProfile)
            .where(
                NormalityProfile.company_id == company_id,
                NormalityProfile.id == profile_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        if profile is None or profile.status != "active":
            raise BaselineAnalysisError(
                "El perfil dejó de estar activo durante el análisis"
            )

        if (
            profile.code != result["profile"]["code"]
            or profile.version != result["profile"]["version"]
        ):
            raise BaselineAnalysisError(
                "El perfil cambió durante el análisis"
            )

        # Comprobamos que las reglas de la salida pertenecen al perfil.
        rule_ids = {item["rule_id"] for item in result["coverage"]}
        rule_rows = list(
            db.scalars(
                select(NormalityRule).where(
                    NormalityRule.company_id == company_id,
                    NormalityRule.profile_id == profile_id,
                    NormalityRule.id.in_(rule_ids),
                )
            ).all()
        )
        rules_by_id = {rule.id: rule for rule in rule_rows}

        if set(rules_by_id) != rule_ids:
            raise BaselineAnalysisError(
                "Las reglas no corresponden al perfil analizado"
            )

        incomplete = any(
            item["status"] != "analyzed"
            for item in result["coverage"]
        )

        execution = AnalysisExecution(
            company_id=company_id,
            profile_id=profile_id,
            profile_code=profile.code,
            profile_version=profile.version,
            detector_version=DETECTOR_VERSION,
            period_start=period_start.astimezone(timezone.utc),
            period_end=period_end.astimezone(timezone.utc),
            data_cutoff_at=data_cutoff_at,
            status="partial" if incomplete else "completed",
            coverage=result["coverage"],
            started_at=started_at,
        )
        db.add(execution)
        db.flush()

        saved_evidence = []

        for item in result["evidence"]:
            rule = rules_by_id.get(item["rule_id"])

            if rule is None:
                raise BaselineAnalysisError(
                    "La evidencia referencia una regla no aplicada"
                )

            # Verificamos la correspondencia entre evidencia y regla.
            if (
                item["source_id"] != rule.source_id
                or item["resource_key"] != rule.resource_key
                or item["metric_name"] != rule.metric_name
                or item["unit"] != rule.unit
                or item["series_key"] != rule.series_key
            ):
                raise BaselineAnalysisError(
                    "La evidencia no corresponde a su regla"
                )

            metric_ids = item["metric_ids"]

            if (
                not metric_ids
                or len(metric_ids) != len(set(metric_ids))
                or len(metric_ids) != item["sample_count"]
            ):
                raise BaselineAnalysisError(
                    "Las referencias de métricas de la evidencia son inválidas"
                )

            # Confirmamos que todas las referencias pertenecen a la serie,
            # al período y al corte utilizados por el análisis.
            metrics = list(
                db.scalars(
                    select(MetricNormalized).where(
                        MetricNormalized.company_id == company_id,
                        MetricNormalized.id.in_(metric_ids),
                        MetricNormalized.source_id == rule.source_id,
                        MetricNormalized.resource_key == rule.resource_key,
                        MetricNormalized.metric_name == rule.metric_name,
                        MetricNormalized.unit == rule.unit,
                        MetricNormalized.observed_at
                        >= execution.period_start,
                        MetricNormalized.observed_at
                        < execution.period_end,
                        MetricNormalized.received_at <= data_cutoff_at,
                    )
                ).all()
            )

            if (
                len(metrics) != len(metric_ids)
                or any(metric.attributes != {} for metric in metrics)
            ):
                raise BaselineAnalysisError(
                    "Una métrica no corresponde a la serie analizada"
                )

            evidence = Evidence(
                company_id=company_id,
                execution_id=execution.id,
                rule_id=rule.id,
                source_id=item["source_id"],
                evidence_type=item["evidence_type"],
                resource_key=item["resource_key"],
                metric_name=item["metric_name"],
                unit=item["unit"],
                series_key=item["series_key"],
                comparison=item["comparison"],
                threshold_value=item["threshold_value"],
                min_observed=item["min_observed"],
                max_observed=item["max_observed"],
                start_at=datetime.fromisoformat(item["start"]),
                end_at=datetime.fromisoformat(item["end"]),
                duration_seconds=item["duration_seconds"],
                sample_count=item["sample_count"],
            )
            db.add(evidence)
            db.flush()

            for metric_id in metric_ids:
                db.add(EvidenceMetric(
                    company_id=company_id,
                    evidence_id=evidence.id,
                    metric_id=metric_id,
                ))

            saved_evidence.append({
                **item,
                "evidence_id": evidence.id,
            })

        execution.finished_at = db.scalar(select(func.clock_timestamp()))

        output = {
            **result,
            "execution_id": execution.id,
            "status": execution.status,
            "data_cutoff_at": data_cutoff_at.isoformat(),
            "evidence": saved_evidence,
        }

        db.commit()
        return output

    except Exception:
        db.rollback()
        raise