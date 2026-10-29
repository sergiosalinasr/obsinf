"""Capacidades implementadas por tecnología; el catálogo no las habilita solo."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


METRICS_JSONL = "obsinf_metrics_jsonl_v1"
WEBLOGIC_LOG = "weblogic_log_v1"


@dataclass(frozen=True)
class TechnologyCapabilities:
    formats: frozenset[str]
    metrics: frozenset[str]


CAPABILITIES: Mapping[str, TechnologyCapabilities] = MappingProxyType({
    "weblogic": TechnologyCapabilities(
        formats=frozenset({METRICS_JSONL, WEBLOGIC_LOG}),
        metrics=frozenset({
            "cpu_usage_percent", "memory_usage_percent",
            "jdbc_active_connections", "http_response_time_ms",
        }),
    ),
    "oracle": TechnologyCapabilities(
        formats=frozenset({METRICS_JSONL}),
        metrics=frozenset({"oracle_active_sessions", "oracle_blocked_sessions"}),
    ),
})


def supports_technology(code: str) -> bool:
    return code in CAPABILITIES


def supports_format(code: str, format_name: str) -> bool:
    capability = CAPABILITIES.get(code)
    return capability is not None and format_name in capability.formats


def supports_metric(code: str, metric_name: str) -> bool:
    capability = CAPABILITIES.get(code)
    return capability is not None and metric_name in capability.metrics
