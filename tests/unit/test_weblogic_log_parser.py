from datetime import timedelta
from io import StringIO

import pytest

from app.integrations.weblogic.log_parser import (
    LogParseError,
    ParsedEvent,
    parse_weblogic_log,
)


FILE_HASH = "a" * 64


def log_record(
    timestamp="2026-10-24T09:00:00-03:00",
    severity="Info",
    server="ManagedServer1",
    message="Server started",
):
    """Genera un registro del perfil explícitamente soportado."""
    return (
        f"####<{timestamp}> <{severity}> <Server> "
        f"<host01> <{server}> <ExecuteThread: '1'> "
        "<kernel> <> <context-01> <1792843200000> "
        f"<BEA-000360> <{message}>\n"
    )


def parse(text, file_hash=FILE_HASH):
    return list(parse_weblogic_log(StringIO(text), file_hash))


def test_valid_log():
    result = parse(log_record())[0]

    assert isinstance(result, ParsedEvent)
    assert result.resource_key == "ManagedServer1"
    assert result.record_type == "log"
    assert result.event_code == "BEA-000360"
    assert result.message == "Server started"
    assert result.occurred_at.hour == 12
    assert result.occurred_at.utcoffset() == timedelta(0)
    assert result.record_locator == "line:1"


def test_multiline_message():
    message = (
        "Request failed\n"
        "java.lang.RuntimeException: example\n"
        "    at example.Service.execute(Service.java:42)"
    )
    results = parse(log_record(severity="Error", message=message))

    assert len(results) == 1
    assert isinstance(results[0], ParsedEvent)
    assert results[0].message == message
    assert results[0].record_locator == "lines:1-3"


@pytest.mark.parametrize(
    "original,normalized",
    [
        ("Info", "info"),
        ("Notice", "info"),
        ("Warning", "warning"),
        ("Error", "error"),
        ("Critical", "critical"),
        ("Debug", "debug"),
        ("Unexpected", "unknown"),
    ],
)
def test_severity_mapping(original, normalized):
    result = parse(log_record(severity=original))[0]

    assert isinstance(result, ParsedEvent)
    assert result.severity == normalized
    assert result.original_severity == original


@pytest.mark.parametrize(
    "timestamp",
    [
        "invalid-date",
        "2026-10-24T09:00:00",
    ],
)
def test_invalid_timestamp(timestamp):
    result = parse(log_record(timestamp=timestamp))[0]

    assert isinstance(result, LogParseError)
    assert result.code == "INVALID_TIMESTAMP"


def test_orphan_line_does_not_hide_next_record():
    results = parse("unexpected content\n" + log_record())

    assert len(results) == 2
    assert isinstance(results[0], LogParseError)
    assert results[0].code == "ORPHAN_LINE"
    assert isinstance(results[1], ParsedEvent)
    assert results[1].record_locator == "line:2"


def test_malformed_record_does_not_stop_next_record():
    results = parse("####<incomplete>\n" + log_record())

    assert len(results) == 2
    assert isinstance(results[0], LogParseError)
    assert results[0].code == "INVALID_LOG_RECORD"
    assert isinstance(results[1], ParsedEvent)


def test_dedup_preserves_repeated_entries():
    text = log_record() + log_record()
    first = parse(text)
    repeated_upload = parse(text)

    assert len(first) == 2
    assert first[0].dedup_key != first[1].dedup_key
    assert first[0].dedup_key == repeated_upload[0].dedup_key
    assert first[1].dedup_key == repeated_upload[1].dedup_key


def test_empty_file():
    result = parse("")[0]

    assert isinstance(result, LogParseError)
    assert result.code == "EMPTY_FILE"


def test_missing_server():
    result = parse(log_record(server=""))[0]

    assert isinstance(result, LogParseError)
    assert result.code == "MISSING_RESOURCE"


def test_initial_bom():
    result = parse("\ufeff" + log_record())[0]

    assert isinstance(result, ParsedEvent)