from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Iterable, Literal


DETECTOR_VERSION = "baseline_deviation:1.0.0"


@dataclass(frozen=True)
class MetricPoint:
    """Medición de una única serie, identificada en PostgreSQL."""

    metric_id: int
    observed_at: datetime
    value: float


@dataclass(frozen=True)
class BaselineRule:
    """Normalidad configurada para una serie específica.

    series_key identifica sus dimensiones normalizadas.
    Por ahora puede usarse "{}" cuando no existen dimensiones.
    """

    company_id: int
    source_id: int
    resource_key: str
    metric_name: str
    unit: str
    profile_code: str
    profile_version: str
    series_key: str

    # Se exige configurar explícitamente el hueco admisible.
    max_gap_seconds: float

    lower_threshold: float | None = None
    upper_threshold: float | None = None
    min_samples: int = 1


@dataclass(frozen=True)
class BaselineDeviation:
    """Evidencia técnica; no clasifica por sí sola un incidente."""

    evidence_type: str
    detector_version: str
    company_id: int
    source_id: int
    resource_key: str
    metric_name: str
    unit: str
    series_key: str
    profile_code: str
    profile_version: str

    comparison: Literal[
        "below_lower_threshold",
        "above_upper_threshold",
    ]
    threshold_value: float
    start: datetime
    end: datetime
    duration_seconds: float
    sample_count: int
    min_observed: float
    max_observed: float
    metric_ids: tuple[int, ...]


def validate_rule(rule: BaselineRule) -> None:
    """Rechaza configuraciones incompletas o contradictorias."""
    if rule.company_id <= 0 or rule.source_id <= 0:
        raise ValueError("Empresa y fuente deben tener IDs positivos")

    for value in (
        rule.resource_key,
        rule.metric_name,
        rule.unit,
        rule.profile_code,
        rule.profile_version,
        rule.series_key,
    ):
        if not value.strip():
            raise ValueError("La regla contiene identificadores vacíos")

    lower = rule.lower_threshold
    upper = rule.upper_threshold

    if lower is None and upper is None:
        raise ValueError("Debe configurar al menos un límite")

    for value in (lower, upper):
        if value is not None and (
            isinstance(value, bool) or not isfinite(value)
        ):
            raise ValueError("Los límites deben ser números finitos")

    if lower is not None and upper is not None and lower > upper:
        raise ValueError("El límite inferior supera al superior")

    if (
        isinstance(rule.max_gap_seconds, bool)
        or not isfinite(rule.max_gap_seconds)
        or rule.max_gap_seconds <= 0
    ):
        raise ValueError("max_gap_seconds debe ser positivo y finito")

    if type(rule.min_samples) is not int or rule.min_samples < 1:
        raise ValueError("min_samples debe ser un entero positivo")


def classify(
    value: float,
    rule: BaselineRule,
) -> Literal[
    "below_lower_threshold",
    "above_upper_threshold",
] | None:
    """Devuelve el lado del rango incumplido o None si es normal."""
    if rule.lower_threshold is not None and value < rule.lower_threshold:
        return "below_lower_threshold"

    if rule.upper_threshold is not None and value > rule.upper_threshold:
        return "above_upper_threshold"

    return None


def detect_baseline_deviations(
    points: Iterable[MetricPoint],
    rule: BaselineRule,
) -> list[BaselineDeviation]:
    """Agrupa muestras desviadas de una única serie.

    El llamador debe separar empresa, fuente, recurso, métrica,
    unidad y dimensiones antes de entregar los puntos.
    No se extrapola la condición fuera de las muestras recibidas.
    """
    validate_rule(rule)
    samples = list(points)

    seen_ids = set()

    for point in samples:
        if type(point.metric_id) is not int or point.metric_id <= 0:
            raise ValueError("metric_id debe ser un entero positivo")

        if point.metric_id in seen_ids:
            raise ValueError("Se recibió un metric_id duplicado")

        seen_ids.add(point.metric_id)

        if (
            point.observed_at.tzinfo is None
            or point.observed_at.utcoffset() is None
        ):
            raise ValueError("Las mediciones requieren zona horaria")

        if isinstance(point.value, bool) or not isfinite(point.value):
            raise ValueError("Las mediciones requieren valores finitos")

    samples.sort(key=lambda point: (point.observed_at, point.metric_id))

    # Dos valores para la misma serie e instante son ambiguos.
    # No imponemos un orden artificial para inferir continuidad.
    for previous, current in zip(samples, samples[1:]):
        if previous.observed_at == current.observed_at:
            raise ValueError(
                "Existen varias mediciones para la misma serie e instante"
            )

    results = []
    current_group = []
    current_side = None
    max_gap = timedelta(seconds=rule.max_gap_seconds)

    def emit_group():
        """Emite el grupo si cumple la cantidad mínima configurada."""
        if len(current_group) < rule.min_samples:
            return

        values = [point.value for point in current_group]
        start = current_group[0].observed_at
        end = current_group[-1].observed_at

        threshold = (
            rule.lower_threshold
            if current_side == "below_lower_threshold"
            else rule.upper_threshold
        )

        results.append(BaselineDeviation(
            evidence_type="BASELINE_DEVIATION",
            detector_version=DETECTOR_VERSION,
            company_id=rule.company_id,
            source_id=rule.source_id,
            resource_key=rule.resource_key,
            metric_name=rule.metric_name,
            unit=rule.unit,
            series_key=rule.series_key,
            profile_code=rule.profile_code,
            profile_version=rule.profile_version,
            comparison=current_side,
            threshold_value=threshold,
            start=start,
            end=end,
            duration_seconds=(end - start).total_seconds(),
            sample_count=len(current_group),
            min_observed=min(values),
            max_observed=max(values),
            metric_ids=tuple(point.metric_id for point in current_group),
        ))

    for point in samples:
        side = classify(point.value, rule)

        if current_group and (
            side != current_side
            or point.observed_at - current_group[-1].observed_at > max_gap
        ):
            emit_group()
            current_group = []
            current_side = None

        if side is not None:
            current_group.append(point)
            current_side = side

    # Conserva también desviaciones presentes al final del período.
    emit_group()

    return results