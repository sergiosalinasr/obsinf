"""Contrato del coordinador sin PostgreSQL, ADK ni llamadas externas."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.analysis.coordinator_contract import (
    CorrelationProposal,
    expected_evidence_overlaps,
    parse_correlation_response,
    validate_correlation_context,
)


@pytest.fixture
def context():
    """Reproduce los intervalos relevantes de la demostración."""
    return {
        "schema_version": "dependency_context:1.0",
        "dependency": {"id": 1},
        "consumer": {
            "finding": {
                "id": 3,
                "event_ids": [5, 6, 7],
            },
            "evidence": [
                {
                    "id": 5,
                    "start_at": "2026-10-27T12:02:00Z",
                    "end_at": "2026-10-27T12:03:00Z",
                },
                {
                    "id": 6,
                    "start_at": "2026-10-27T12:05:00Z",
                    "end_at": "2026-10-27T12:06:00Z",
                },
            ],
        },
        "provider": {
            "finding": {
                "id": 4,
                "event_ids": [],
            },
            "evidence": [
                {
                    "id": 7,
                    "start_at": "2026-10-27T12:02:00Z",
                    "end_at": "2026-10-27T12:04:00Z",
                },
            ],
        },
    }


@pytest.fixture
def payload():
    return {
        "dependency_id": 1,
        "finding_ids": [3, 4],
        "evidence_ids": [5, 6, 7],
        "event_ids": [5, 6],
        "assessment": "TEMPORAL_COINCIDENCE",
        "causality": "NOT_ESTABLISHED",
        "confidence": 0.7,
        "summary": (
            "La ventana JDBC superior coincide parcialmente con la "
            "evidencia Oracle. La desviación JDBC inferior ocurre después."
        ),
        "evidence_overlaps": [
            {
                "consumer_evidence_id": 5,
                "provider_evidence_id": 7,
            }
        ],
        "limitations": [
            "La coincidencia temporal no demuestra causalidad."
        ],
    }


def test_valid_response(context, payload):
    proposal = parse_correlation_response(
        json.dumps(payload), context
    )
    assert proposal.finding_ids == [3, 4]


def test_only_upper_jdbc_window_overlaps(context):
    assert expected_evidence_overlaps(context) == {(5, 7)}


def test_nonoverlapping_evidence(context, payload):
    modified = deepcopy(context)
    modified["provider"]["evidence"][0].update(
        start_at="2026-10-27T12:07:00Z",
        end_at="2026-10-27T12:07:30Z",
    )
    payload["assessment"] = "NO_TEMPORAL_COINCIDENCE"
    payload["evidence_overlaps"] = []

    validate_correlation_context(
        CorrelationProposal.model_validate(payload), modified
    )


def test_point_overlap(context):
    context["provider"]["evidence"][0].update(
        start_at="2026-10-27T12:03:00Z",
        end_at="2026-10-27T12:03:00Z",
    )
    assert expected_evidence_overlaps(context) == {(5, 7)}


@pytest.mark.parametrize(
    "changes",
    [
        {"dependency_id": True},
        {"finding_ids": [3, "4"]},
        {"finding_ids": [3, 3]},
        {"evidence_ids": [5, 6, 6]},
        {"event_ids": [5, 5]},
        {"confidence": True},
        {"confidence": "0.7"},
        {"confidence": -0.1},
        {"confidence": 1.1},
        {"confidence": float("nan")},
        {"causality": "CONFIRMED"},
        {"summary": "   "},
        {"limitations": []},
        {"limitations": ["   "]},
        {"company_id": 1},
    ],
)
def test_rejects_invalid_structure(payload, changes):
    payload.update(changes)

    with pytest.raises(ValidationError):
        CorrelationProposal.model_validate(payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"dependency_id": 99},
        {"finding_ids": [3, 99]},
        {"evidence_ids": [5, 7]},
        {"evidence_ids": [5, 6, 7, 99]},
        {"event_ids": [99]},
        {"evidence_overlaps": []},
        {
            "evidence_overlaps": [
                {
                    "consumer_evidence_id": 6,
                    "provider_evidence_id": 7,
                }
            ]
        },
        {"assessment": "NO_TEMPORAL_COINCIDENCE"},
    ],
)
def test_rejects_invalid_context(context, payload, changes):
    payload.update(changes)
    proposal = CorrelationProposal.model_validate(payload)

    with pytest.raises(ValueError):
        validate_correlation_context(proposal, context)


def test_duplicate_overlap(context, payload):
    payload["evidence_overlaps"] *= 2
    proposal = CorrelationProposal.model_validate(payload)

    with pytest.raises(ValueError, match="repetirse"):
        validate_correlation_context(proposal, context)


def test_rejects_markdown(context, payload):
    response = "```json\n" + json.dumps(payload) + "\n```"

    with pytest.raises(ValidationError):
        parse_correlation_response(response, context)


def test_rejects_unknown_context_version(context, payload):
    context["schema_version"] = "unknown"

    with pytest.raises(ValueError, match="Versión"):
        parse_correlation_response(json.dumps(payload), context)