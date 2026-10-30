"""Persistencia de correlaciones sin llamadas al LLM."""

from copy import deepcopy

import pytest
from sqlalchemy import func, select

from test_dependency_context import joint_context
from test_oracle_findings import oracle_contexts

from app.agents.specialist_runtime import AgentConfiguration
from app.analysis.coordinator_contract import (
    CorrelationProposal,
    expected_evidence_overlaps,
)
from app.models.correlation import Correlation
from app.services.correlations import (
    CorrelationError,
    ensure_correlation_not_saved,
    save_correlation,
)
from app.services.dependency_context import build_dependency_context


def prepare(db, joint):
    context = build_dependency_context(
        db,
        company_id=joint["company_id"],
        dependency_id=joint["dependency"].id,
        consumer_finding_id=joint["consumer"].id,
        provider_finding_id=joint["provider"].id,
    )
    sides = [context["consumer"], context["provider"]]
    pairs = sorted(expected_evidence_overlaps(context))

    proposal = CorrelationProposal(
        dependency_id=context["dependency"]["id"],
        finding_ids=[side["finding"]["id"] for side in sides],
        evidence_ids=[
            evidence["id"]
            for side in sides
            for evidence in side["evidence"]
        ],
        event_ids=[],
        assessment=(
            "TEMPORAL_COINCIDENCE"
            if pairs else "NO_TEMPORAL_COINCIDENCE"
        ),
        causality="NOT_ESTABLISHED",
        confidence=0.7,
        summary="Síntesis de prueba sustentada en las evidencias seleccionadas.",
        evidence_overlaps=[
            {
                "consumer_evidence_id": consumer,
                "provider_evidence_id": provider,
            }
            for consumer, provider in pairs
        ],
        limitations=["La coincidencia temporal no demuestra causalidad."],
    )
    configuration = AgentConfiguration(
        agent_name="dependency_coordinator",
        model_name="openai/test-model",
        instruction="Instrucción de prueba",
    )
    return context, proposal, configuration


def save(db, joint, context, proposal, configuration):
    return save_correlation(
        db,
        company_id=joint["company_id"],
        context=context,
        proposal=proposal,
        configuration=configuration,
    )


def test_saves_snapshot(db_session, joint_context):
    context, proposal, configuration = prepare(db_session, joint_context)
    original = deepcopy(context)

    saved = save(
        db_session, joint_context, context, proposal, configuration
    )
    saved_id = saved.id

    context["dependency"]["description"] = "Cambio del objeto del llamador"
    db_session.expire_all()
    stored = db_session.get(Correlation, saved_id)

    assert stored.context_snapshot == original
    assert stored.proposal == proposal.model_dump(mode="json")
    assert stored.agent_name == "dependency_coordinator"
    assert len(stored.prompt_sha256) == 64
    assert len(stored.context_sha256) == 64


def test_duplicate_and_preflight(db_session, joint_context):
    context, proposal, configuration = prepare(db_session, joint_context)
    save(db_session, joint_context, context, proposal, configuration)

    with pytest.raises(CorrelationError) as caught:
        ensure_correlation_not_saved(
            db_session,
            company_id=joint_context["company_id"],
            context=context,
            configuration=configuration,
        )
    assert caught.value.code == "CORRELATION_EXISTS"

    with pytest.raises(CorrelationError) as caught:
        save(db_session, joint_context, context, proposal, configuration)
    assert caught.value.code == "CORRELATION_EXISTS"

    assert db_session.scalar(
        select(func.count()).select_from(Correlation).where(
            Correlation.company_id == joint_context["company_id"]
        )
    ) == 1


def test_changed_context_is_rejected(db_session, joint_context):
    context, proposal, configuration = prepare(db_session, joint_context)

    joint_context["dependency"].description = "Configuración modificada"
    db_session.flush()

    with pytest.raises(CorrelationError) as caught:
        save(db_session, joint_context, context, proposal, configuration)

    assert caught.value.code == "CONTEXT_CHANGED"


def test_foreign_company_is_rejected(db_session, joint_context):
    context, proposal, configuration = prepare(db_session, joint_context)

    with pytest.raises(CorrelationError) as caught:
        save_correlation(
            db_session,
            company_id=joint_context["company_id"] + 1,
            context=context,
            proposal=proposal,
            configuration=configuration,
        )

    assert caught.value.code == "INVALID_COMPANY"


def test_invalid_reference_is_rejected(db_session, joint_context):
    context, proposal, configuration = prepare(db_session, joint_context)
    values = proposal.model_dump(mode="json")
    values["event_ids"] = [999999]
    invalid = CorrelationProposal.model_validate(values)

    with pytest.raises(ValueError):
        save(db_session, joint_context, context, invalid, configuration)

    assert db_session.scalar(
        select(func.count()).select_from(Correlation).where(
            Correlation.company_id == joint_context["company_id"]
        )
    ) == 0