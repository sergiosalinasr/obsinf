import json

import pytest

from app.agents.weblogic_agent import parse_agent_response


def evidence():
    return [
        {
            "id": 1,
            "resource_key": "ManagedServer1",
            "start_at": "2026-10-27T12:02:00+00:00",
            "end_at": "2026-10-27T12:03:00+00:00",
        },
        {
            "id": 2,
            "resource_key": "ManagedServer1",
            "start_at": "2026-10-27T12:05:00+00:00",
            "end_at": "2026-10-27T12:06:00+00:00",
        },
    ]


def proposal():
    return {
        "resource_key": "ManagedServer1",
        "start": "2026-10-27T12:02:00Z",
        "end": "2026-10-27T12:06:00Z",
        "classification": "ANOMALY",
        "severity": "MEDIUM",
        "confidence": 0.8,
        "finding": "Se observaron desviaciones del rango configurado.",
        "evidence_ids": [1, 2],
        "possible_implications": [],
    }


def test_valid_agent_response():
    result = parse_agent_response(
        json.dumps(proposal()),
        resource_key="ManagedServer1",
        evidence=evidence(),
    )

    assert result.evidence_ids == [1, 2]
    assert result.classification == "ANOMALY"


def test_rejects_unknown_evidence():
    data = proposal()
    data["evidence_ids"] = [99]

    with pytest.raises(ValueError, match="no disponibles"):
        parse_agent_response(
            json.dumps(data),
            resource_key="ManagedServer1",
            evidence=evidence(),
        )


def test_rejects_wrong_resource():
    data = proposal()
    data["resource_key"] = "ManagedServer2"

    with pytest.raises(ValueError, match="recurso"):
        parse_agent_response(
            json.dumps(data),
            resource_key="ManagedServer1",
            evidence=evidence(),
        )


def test_rejects_invalid_json():
    with pytest.raises(ValueError, match="JSON válido"):
        parse_agent_response(
            "Esto no es JSON",
            resource_key="ManagedServer1",
            evidence=evidence(),
        )