from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.analysis.finding_contract import (
    FindingProposal,
    validate_finding_context,
)


def valid_proposal():
    """Propuesta sintética basada en las evidencias JDBC."""
    return {
        "resource_key": "ManagedServer1",
        "start": "2026-10-27T12:02:00Z",
        "end": "2026-10-27T12:06:00Z",
        "classification": "ANOMALY",
        "severity": "MEDIUM",
        "confidence": 0.8,
        "finding": (
            "Las conexiones JDBC se encontraron fuera del rango "
            "configurado en dos períodos."
        ),
        "evidence_ids": [1, 2],
        "possible_implications": [
            "Conviene revisar la configuración y el comportamiento del pool."
        ],
    }


def periods():
    return {
        1: (
            datetime(2026, 10, 27, 12, 2, tzinfo=timezone.utc),
            datetime(2026, 10, 27, 12, 3, tzinfo=timezone.utc),
        ),
        2: (
            datetime(2026, 10, 27, 12, 5, tzinfo=timezone.utc),
            datetime(2026, 10, 27, 12, 6, tzinfo=timezone.utc),
        ),
    }


def test_valid_finding_and_context():
    proposal = FindingProposal.model_validate(valid_proposal())

    validate_finding_context(
        proposal,
        expected_resource="ManagedServer1",
        allowed_evidence_ids={1, 2},
        evidence_periods=periods(),
    )

    assert proposal.classification == "ANOMALY"
    assert proposal.evidence_ids == [1, 2]


@pytest.mark.parametrize(
    "changes",
    [
        {"classification": "UNKNOWN"},
        {"severity": "EXTREME"},
        {"confidence": -0.1},
        {"confidence": 1.1},
        {"confidence": True},
        {"confidence": float("nan")},
        {"evidence_ids": []},
        {"evidence_ids": [1, 1]},
        {"evidence_ids": [0]},
        {"start": "2026-10-27T12:02:00"},
        {"start": "2026-10-27T12:07:00Z"},
        {"finding": "  "},
        {"company_id": 999},
    ],
)
def test_rejects_invalid_proposal(changes):
    payload = deepcopy(valid_proposal())
    payload.update(changes)

    with pytest.raises(ValidationError):
        FindingProposal.model_validate(payload)


def test_rejects_evidence_not_in_context():
    payload = valid_proposal()
    payload["evidence_ids"] = [1, 99]
    proposal = FindingProposal.model_validate(payload)

    with pytest.raises(ValueError, match="no disponibles"):
        validate_finding_context(
            proposal,
            expected_resource="ManagedServer1",
            allowed_evidence_ids={1, 2},
            evidence_periods=periods(),
        )


def test_rejects_other_resource():
    proposal = FindingProposal.model_validate(valid_proposal())

    with pytest.raises(ValueError, match="recurso"):
        validate_finding_context(
            proposal,
            expected_resource="ManagedServer2",
            allowed_evidence_ids={1, 2},
            evidence_periods=periods(),
        )


def test_rejects_period_that_does_not_cover_evidence():
    payload = valid_proposal()
    payload["end"] = "2026-10-27T12:03:00Z"
    proposal = FindingProposal.model_validate(payload)

    with pytest.raises(ValueError, match="no cubre"):
        validate_finding_context(
            proposal,
            expected_resource="ManagedServer1",
            allowed_evidence_ids={1, 2},
            evidence_periods=periods(),
        )


def test_rejects_missing_evidence_period():
    proposal = FindingProposal.model_validate(valid_proposal())

    with pytest.raises(ValueError, match="Faltan períodos"):
        validate_finding_context(
            proposal,
            expected_resource="ManagedServer1",
            allowed_evidence_ids={1, 2},
            evidence_periods={1: periods()[1]},
        )
