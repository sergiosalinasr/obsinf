"""Compatibilidad con la ruta anterior del parser de métricas.

La implementación común es única: se reexportan las mismas clases y
funciones para conservar imports, isinstance y claves de deduplicación.
"""

from app.integrations.common.metrics_jsonl import (
    METRIC_UNITS,
    PARSER_VERSION,
    MetricInput,
    ParseError,
    ParsedMetric,
    dedup_key_for,
    parse_metrics_jsonl,
    reject_nonstandard_number,
    unique_object,
)


__all__ = [
    "METRIC_UNITS", "PARSER_VERSION", "MetricInput", "ParseError",
    "ParsedMetric", "dedup_key_for", "parse_metrics_jsonl",
    "reject_nonstandard_number", "unique_object",
]
