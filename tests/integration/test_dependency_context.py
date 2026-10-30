"""Selección conjunta de hallazgos WebLogic y Oracle."""

from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import select

from test_oracle_findings import oracle_contexts, persist
from app.models.analysis import Evidence
from app.models.finding import Finding, FindingEvidence
from app.models.normality import NormalityRule
from app.models.source import Source
from app.models.technology import Technology
from app.schemas.resource_dependency import DependencyCreate
from app.services.dependency_context import (
    DependencyContextError,
    build_dependency_context,
)
from app.services.resource_dependencies import create_dependency


@pytest.fixture
def joint_context(db_session, oracle_contexts):
    """Agrega un consumidor WebLogic al contexto Oracle existente."""
    oracle = oracle_contexts[0]
    oracle_finding = persist(db_session, oracle)

    technology = db_session.scalar(
        select(Technology).where(Technology.code == "weblogic")
    )
    assert technology is not None

    source = Source(
        company_id=oracle["company"].id,
        technology_id=technology.id,
        code="WL_CONTEXT",
        name="WebLogic de contexto",
        source_timezone="America/Santiago",
    )
    db_session.add(source)
    db_session.flush()

    rule = NormalityRule(
        company_id=oracle["company"].id,
        profile_id=oracle["execution"].profile_id,
        source_id=source.id,
        resource_key="ManagedServer1",
        metric_name="jdbc_active_connections",
        unit="count",
        dimensions={},
        series_key="{}",
        upper_threshold=55,
        min_samples=1,
        max_gap_seconds=90,
    )
    db_session.add(rule)
    db_session.flush()

    evidence = Evidence(
        company_id=oracle["company"].id,
        execution_id=oracle["execution"].id,
        rule_id=rule.id,
        source_id=source.id,
        evidence_type="BASELINE_DEVIATION",
        resource_key="ManagedServer1",
        metric_name="jdbc_active_connections",
        unit="count",
        series_key="{}",
        comparison="above_upper_threshold",
        threshold_value=55,
        min_observed=60,
        max_observed=60,
        start_at=oracle["evidence"].start_at,
        end_at=oracle["evidence"].start_at,
        duration_seconds=0,
        sample_count=1,
    )
    db_session.add(evidence)
    db_session.flush()

    finding = Finding(
        company_id=oracle["company"].id,
        execution_id=oracle["execution"].id,
        source_id=source.id,
        resource_key="ManagedServer1",
        start_at=evidence.start_at,
        end_at=evidence.end_at,
        classification="ANOMALY",
        severity="LOW",
        confidence=0.7,
        finding="Una muestra JDBC supera el perfil configurado.",
        possible_implications=[],
        event_context={},
        agent_name="weblogic_specialist",
        model_name="test-model",
        prompt_sha256="a" * 64,
    )
    db_session.add(finding)
    db_session.flush()
    db_session.add(
        FindingEvidence(
            company_id=finding.company_id,
            finding_id=finding.id,
            evidence_id=evidence.id,
        )
    )
    db_session.flush()

    dependency = create_dependency(
        db_session,
        oracle["company"].id,
        DependencyCreate(
            consumer_source_id=source.id,
            consumer_resource_key="ManagedServer1",
            provider_source_id=oracle["source"].id,
            provider_resource_key=oracle["evidence"].resource_key,
            description="Relación sintética de prueba",
        ),
        configured_by="pytest",
    )

    return {
        "company_id": oracle["company"].id,
        "dependency": dependency,
        "consumer": finding,
        "provider": oracle_finding,
        "oracle": oracle,
    }


def build(db, context, **changes):
    values = {
        "company_id": context["company_id"],
        "dependency_id": context["dependency"].id,
        "consumer_finding_id": context["consumer"].id,
        "provider_finding_id": context["provider"].id,
    }
    values.update(changes)
    return build_dependency_context(db, **values)


def test_valid_context(db_session, joint_context):
    context = build(db_session, joint_context)

    assert context["consumer"]["source"]["technology"] == "weblogic"
    assert context["provider"]["source"]["technology"] == "oracle"
    assert context["comparison"]["findings_overlap"] is True
    assert context["provider"]["evidence"][0]["metric_name"] == (
        "oracle_blocked_sessions"
    )
    assert context["provider"]["finding"]["event_ids"] == []


def test_snapshot_is_independent(db_session, joint_context):
    context = build(db_session, joint_context)
    original = deepcopy(joint_context["provider"].possible_implications)

    context["provider"]["finding"]["possible_implications"].append(
        "Cambio local"
    )

    assert joint_context["provider"].possible_implications == original


def test_inactive_dependency(db_session, joint_context):
    joint_context["dependency"].is_active = False
    db_session.flush()

    with pytest.raises(DependencyContextError) as caught:
        build(db_session, joint_context)

    assert caught.value.code == "DEPENDENCY_INACTIVE"


def test_foreign_dependency(db_session, joint_context, oracle_contexts):
    with pytest.raises(DependencyContextError) as caught:
        build(
            db_session,
            joint_context,
            company_id=oracle_contexts[1]["company"].id,
        )

    assert caught.value.code == "DEPENDENCY_NOT_FOUND"


def test_foreign_finding(db_session, joint_context, oracle_contexts):
    foreign = persist(db_session, oracle_contexts[1])

    with pytest.raises(DependencyContextError) as caught:
        build(
            db_session,
            joint_context,
            provider_finding_id=foreign.id,
        )

    assert caught.value.code == "FINDING_NOT_FOUND"


def test_swapped_findings(db_session, joint_context):
    with pytest.raises(DependencyContextError) as caught:
        build(
            db_session,
            joint_context,
            consumer_finding_id=joint_context["provider"].id,
            provider_finding_id=joint_context["consumer"].id,
        )

    assert caught.value.code == "FINDING_NOT_FOUND"


@pytest.mark.parametrize("status", ["processing", "failed"])
def test_execution_not_ready(db_session, joint_context, status):
    joint_context["oracle"]["execution"].status = status
    db_session.flush()

    with pytest.raises(DependencyContextError) as caught:
        build(db_session, joint_context)

    assert caught.value.code == "ANALYSIS_NOT_READY"


def test_partial_coverage_is_preserved(db_session, joint_context):
    execution = joint_context["oracle"]["execution"]
    execution.status = "partial"
    execution.coverage = [{"status": "no_data", "rule_id": 123}]
    db_session.flush()

    context = build(db_session, joint_context)

    assert context["provider"]["execution"]["status"] == "partial"
    assert context["provider"]["execution"]["coverage"] == execution.coverage


def test_invalid_id(db_session, joint_context):
    with pytest.raises(DependencyContextError) as caught:
        build(db_session, joint_context, dependency_id=True)

    assert caught.value.code == "INVALID_ID"


def test_invalid_finding_period(db_session, joint_context):
    finding = joint_context["consumer"]
    execution = joint_context["oracle"]["execution"]
    finding.start_at = execution.period_end
    finding.end_at = execution.period_end + timedelta(minutes=1)
    db_session.flush()

    with pytest.raises(DependencyContextError) as caught:
        build(db_session, joint_context)

    assert caught.value.code == "INVALID_FINDING_PERIOD"