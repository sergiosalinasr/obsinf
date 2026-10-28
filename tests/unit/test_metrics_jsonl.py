import json
from datetime import timedelta
from io import StringIO

import pytest

from app.integrations.weblogic.metrics_jsonl import (
    ParseError,
    ParsedMetric,
    parse_metrics_jsonl,
)


def valid_payload(**changes):
    """Construye una medición válida para las pruebas."""
    payload = {
        "timestamp": "2026-10-24T09:00:00-03:00",
        "resource_key": "ManagedServer1",
        "metric_name": "cpu_usage_percent",
        "value": 46.5,
        "unit": "percent",
        "attributes": {},
    }
    payload.update(changes)
    return payload


def parse_one(payload):
    results = list(
        parse_metrics_jsonl(StringIO(json.dumps(payload)))
    )
    assert len(results) == 1
    return results[0]


def test_normalizes_timestamp_and_preserves_origin():
    result = parse_one(valid_payload())

    assert isinstance(result, ParsedMetric)
    assert result.metric.timestamp.hour == 12
    assert result.metric.timestamp.utcoffset() == timedelta(0)
    assert result.record_locator == "line:1"
    assert len(result.dedup_key) == 64


@pytest.mark.parametrize(
    "name,value,unit",
    [
        ("cpu_usage_percent", 0, "percent"),
        ("cpu_usage_percent", 100, "percent"),
        ("memory_usage_percent", 65.2, "percent"),
        ("jdbc_active_connections", 12, "count"),
        ("http_response_time_ms", 150.5, "ms"),
    ],
)
def test_accepts_supported_metrics(name, value, unit):
    result = parse_one(
        valid_payload(metric_name=name, value=value, unit=unit)
    )

    assert isinstance(result, ParsedMetric)


@pytest.mark.parametrize(
    "changes",
    [
        {"timestamp": "2026-10-24T09:00:00"},
        {"timestamp": 1792843200},
        {"resource_key": "   "},
        {"metric_name": "unknown_metric"},
        {"value": "46.5"},
        {"value": True},
        {"value": -1},
        {"value": 101},
        {"unit": "ms"},
        {
            "metric_name": "jdbc_active_connections",
            "unit": "count",
            "value": 1.5,
        },
        {
            "metric_name": "http_response_time_ms",
            "unit": "ms",
            "value": -1,
        },
        {"company_id": 99},
        {"attributes": []},
        {"attributes": {"nested": float("inf")}},
    ],
)
def test_rejects_invalid_metrics(changes):
    result = parse_one(valid_payload(**changes))

    assert isinstance(result, ParseError)


def test_continues_after_invalid_line():
    valid_line = json.dumps(valid_payload())
    text = f"{valid_line}\nnot-json\n{valid_line}\n"

    results = list(parse_metrics_jsonl(StringIO(text)))

    assert len(results) == 3
    assert isinstance(results[0], ParsedMetric)
    assert isinstance(results[1], ParseError)
    assert isinstance(results[2], ParsedMetric)
    assert results[1].line_number == 2
    assert results[2].line_number == 3


def test_dedup_uses_normalized_content():
    """Orden de claves y zonas equivalentes producen la misma huella."""
    first = parse_one(
        valid_payload(
            value=46,
            attributes={"host": "server1", "environment": "prod"},
        )
    )
    second = parse_one(
        valid_payload(
            timestamp="2026-10-24T12:00:00Z",
            value=46.0,
            attributes={"environment": "prod", "host": "server1"},
        )
    )
    different = parse_one(
        valid_payload(value=47)
    )

    assert isinstance(first, ParsedMetric)
    assert isinstance(second, ParsedMetric)
    assert isinstance(different, ParsedMetric)
    assert first.dedup_key == second.dedup_key
    assert first.dedup_key != different.dedup_key


@pytest.mark.parametrize(
    "text,expected_code",
    [
        ("", "EMPTY_FILE"),
        ("\n", "EMPTY_LINE"),
        ("[]", "INVALID_RECORD"),
        ('{"value": NaN}', "INVALID_JSON"),
        ('{"value": Infinity}', "INVALID_JSON"),
        ('{"value": 1, "value": 2}', "INVALID_JSON"),
    ],
)
def test_invalid_json_records(text, expected_code):
    results = list(parse_metrics_jsonl(StringIO(text)))

    assert len(results) == 1
    assert isinstance(results[0], ParseError)
    assert results[0].code == expected_code


def test_accepts_initial_bom():
    text = "\ufeff" + json.dumps(valid_payload())

    results = list(parse_metrics_jsonl(StringIO(text)))

    assert isinstance(results[0], ParsedMetric)