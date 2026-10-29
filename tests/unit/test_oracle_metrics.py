"""Capacidades por tecnología, validación Oracle y compatibilidad del parser."""

import json

import pytest

from app.integrations.capabilities import supports_format, supports_metric
from app.integrations.common.metrics_jsonl import ParseError, ParsedMetric, parse_metrics_jsonl
from app.integrations.weblogic import metrics_jsonl as legacy
from app.integrations.common import metrics_jsonl as common


def payload(name="oracle_active_sessions", value=5, unit="count", **changes):
    data = {
        "timestamp": "2026-10-27T09:00:00-03:00",
        "resource_key": "ORCLPDB1/ERP_SERVICE", "metric_name": name,
        "value": value, "unit": unit, "attributes": {},
    }
    data.update(changes)
    return data


def parse(data):
    return list(parse_metrics_jsonl([json.dumps(data)]))[0]


@pytest.mark.parametrize("technology,format_name,expected", [
    ("weblogic", "obsinf_metrics_jsonl_v1", True),
    ("weblogic", "weblogic_log_v1", True),
    ("oracle", "obsinf_metrics_jsonl_v1", True),
    ("oracle", "weblogic_log_v1", False),
    ("oracle", "unknown", False),
    ("unknown", "obsinf_metrics_jsonl_v1", False),
])
def test_format_capabilities(technology, format_name, expected):
    assert supports_format(technology, format_name) is expected


@pytest.mark.parametrize("technology,name,expected", [
    ("oracle", "oracle_active_sessions", True),
    ("oracle", "oracle_blocked_sessions", True),
    ("oracle", "jdbc_active_connections", False),
    ("weblogic", "oracle_blocked_sessions", False),
    ("weblogic", "jdbc_active_connections", True),
    ("unknown", "oracle_blocked_sessions", False),
])
def test_metric_capabilities(technology, name, expected):
    assert supports_metric(technology, name) is expected


@pytest.mark.parametrize("name", ["oracle_active_sessions", "oracle_blocked_sessions"])
@pytest.mark.parametrize("value", [0, 5])
def test_accepts_nonnegative_oracle_session_counts(name, value):
    result = parse(payload(name, value))
    assert isinstance(result, ParsedMetric)
    assert result.metric.timestamp.hour == 12
    assert result.metric.value == value
    assert result.metric.unit == "count"


@pytest.mark.parametrize("name", ["oracle_active_sessions", "oracle_blocked_sessions"])
@pytest.mark.parametrize("value", [-1, 1.5, True, "5"])
def test_rejects_invalid_oracle_counts(name, value):
    result = parse(payload(name, value))
    assert isinstance(result, ParseError)
    assert result.code == "INVALID_METRIC"


@pytest.mark.parametrize("name", ["oracle_active_sessions", "oracle_blocked_sessions"])
def test_rejects_wrong_oracle_unit(name):
    assert isinstance(parse(payload(name, unit="percent")), ParseError)


def test_legacy_route_reexports_identical_objects():
    assert legacy.ParsedMetric is common.ParsedMetric
    assert legacy.ParseError is common.ParseError
    assert legacy.MetricInput is common.MetricInput
    assert legacy.parse_metrics_jsonl is common.parse_metrics_jsonl


def test_different_oracle_metric_names_are_not_duplicates():
    first = parse(payload("oracle_active_sessions"))
    second = parse(payload("oracle_blocked_sessions"))
    assert first.dedup_key != second.dedup_key


def test_oracle_timezone_and_integer_representation_are_normalized():
    first = parse(payload(value=5))
    second = parse(payload(value=5.0, timestamp="2026-10-27T12:00:00Z"))
    assert first.dedup_key == second.dedup_key


@pytest.mark.parametrize("name,value,unit,expected", [
    ("cpu_usage_percent", 46.5, "percent", "984b0b250cd7c328685c7f7c24310671c51ad2873ed9c5b1be5ee5d1484028f5"),
    ("memory_usage_percent", 65.2, "percent", "f2ca709bb63d0400a5ba677f3c80114a61d595e8f7122afbc7a6ba63b39338e5"),
    ("jdbc_active_connections", 12, "count", "cc31fdaae242e8a333a82ee70e71a646136fec81726dd57fb475e162a74dc445"),
    ("http_response_time_ms", 150.5, "ms", "0231c794244acc478b71331ef1160c804c38284c987c99fe0848f1808630470d"),
])
def test_existing_metric_fingerprints_remain_unchanged(name, value, unit, expected):
    """Huellas obtenidas del parser 1.0.0 antes de moverlo o ampliarlo."""
    result = parse(payload(
        name, value, unit, timestamp="2026-10-24T09:00:00-03:00",
        resource_key="ManagedServer1",
    ))
    assert result.dedup_key == expected
