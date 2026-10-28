import json

import pytest

from app.agents.weblogic_prompt import (
    build_weblogic_message,
    load_weblogic_instruction,
)


def example_evidence():
    return [
        {
            "id": 1,
            "resource_key": "ManagedServer1",
            "comparison": "above_upper_threshold",
            "threshold_value": 55,
            "min_observed": 58,
            "max_observed": 62,
            "start_at": "2026-10-27T12:02:00Z",
            "end_at": "2026-10-27T12:03:00Z",
        },
        {
            "id": 2,
            "resource_key": "ManagedServer1",
            "comparison": "below_lower_threshold",
            "threshold_value": 20,
            "min_observed": 15,
            "max_observed": 18,
            "start_at": "2026-10-27T12:05:00Z",
            "end_at": "2026-10-27T12:06:00Z",
        },
    ]


def test_load_instruction():
    instruction = load_weblogic_instruction()

    assert "evidence_ids" in instruction
    assert "ANOMALY" in instruction
    assert "DEGRADATION" in instruction


def test_build_message_contains_expected_data():
    message = build_weblogic_message(
        "ManagedServer1",
        example_evidence(),
    )

    payload = json.loads(message.split("DATOS:\n", 1)[1])

    assert payload["resource_key"] == "ManagedServer1"
    assert [item["id"] for item in payload["evidence"]] == [1, 2]


def test_rejects_empty_evidence():
    with pytest.raises(ValueError, match="al menos una evidencia"):
        build_weblogic_message("ManagedServer1", [])


def test_rejects_different_resource():
    evidence = example_evidence()
    evidence[1]["resource_key"] = "ManagedServer2"

    with pytest.raises(ValueError, match="mismo recurso"):
        build_weblogic_message("ManagedServer1", evidence)


def test_rejects_duplicate_evidence_ids():
    evidence = example_evidence()
    evidence[1]["id"] = 1

    with pytest.raises(ValueError, match="repetirse"):
        build_weblogic_message("ManagedServer1", evidence)


def test_rejects_non_json_values():
    evidence = example_evidence()
    evidence[0]["threshold_value"] = float("nan")

    with pytest.raises(ValueError, match="JSON válido"):
        build_weblogic_message("ManagedServer1", evidence)