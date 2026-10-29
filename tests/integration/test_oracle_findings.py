"""Lectura y persistencia Oracle sin invocar modelos externos."""

import hashlib
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.analysis.event_context import EventContext, EventWindow
from app.analysis.finding_contract import FindingProposal
from app.jobs import interpret_oracle
from app.models.analysis import AnalysisExecution, Evidence
from app.models.company import Company
from app.models.finding import Finding, FindingEvidence, FindingEvent
from app.models.normality import NormalityProfile, NormalityRule
from app.models.source import Source
from app.models.technology import Technology
from app.services.findings import FindingPersistenceError, save_finding


@pytest.fixture
def oracle_contexts(db_session, monkeypatch):
    technology = db_session.scalar(select(Technology).where(Technology.code == "oracle"))
    assert technology is not None, "Oracle debe estar registrado en obsinf_test"
    start = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    contexts = []
    for index in range(2):
        company = Company(code=f"TEST_{uuid4().hex[:12]}", name=f"Empresa Oracle {index}")
        db_session.add(company)
        db_session.flush()
        source = Source(
            company_id=company.id, technology_id=technology.id, code="ORACLE_TEST",
            name="Oracle de prueba", source_timezone="America/Santiago",
        )
        profile = NormalityProfile(
            company_id=company.id, code="ORACLE_PROFILE", version="1", name="Perfil Oracle",
        )
        db_session.add_all([source, profile])
        db_session.flush()
        rule = NormalityRule(
            company_id=company.id, profile_id=profile.id, source_id=source.id,
            resource_key="ORCLPDB1/ERP_SERVICE", metric_name="oracle_blocked_sessions",
            unit="count", dimensions={}, series_key="{}", upper_threshold=0,
            min_samples=2, max_gap_seconds=90,
        )
        execution = AnalysisExecution(
            company_id=company.id, profile_id=profile.id, profile_code=profile.code,
            profile_version=profile.version, detector_version="baseline_deviation:1.0.0",
            period_start=start, period_end=start + timedelta(minutes=8),
            data_cutoff_at=start + timedelta(hours=3), status="completed",
        )
        db_session.add_all([rule, execution])
        db_session.flush()
        evidence = Evidence(
            company_id=company.id, execution_id=execution.id, rule_id=rule.id,
            source_id=source.id, evidence_type="BASELINE_DEVIATION",
            resource_key="ORCLPDB1/ERP_SERVICE", metric_name="oracle_blocked_sessions",
            unit="count", series_key="{}", comparison="above_upper_threshold",
            threshold_value=0, min_observed=2, max_observed=4,
            start_at=start + timedelta(minutes=2), end_at=start + timedelta(minutes=4),
            duration_seconds=120, sample_count=3,
        )
        db_session.add(evidence)
        db_session.flush()
        contexts.append({"company": company, "source": source, "execution": execution, "evidence": evidence})
    monkeypatch.setattr(interpret_oracle, "SessionLocal", lambda: nullcontext(db_session))
    return contexts


def proposal(context, **changes):
    evidence = context["evidence"]
    values = {
        "resource_key": evidence.resource_key, "start": evidence.start_at, "end": evidence.end_at,
        "classification": "ANOMALY", "severity": "LOW", "confidence": 0.7,
        "finding": "Se observaron tres muestras de sesiones bloqueadas sobre el umbral.",
        "evidence_ids": [evidence.id], "event_ids": [], "possible_implications": [],
    }
    values.update(changes)
    return FindingProposal.model_validate(values)


def persist(db, context, **changes):
    values = {
        "company_id": context["company"].id, "source_id": context["source"].id,
        "execution_id": context["execution"].id, "proposal": proposal(context),
        "agent_name": "oracle_specialist", "model_name": "openai/test-model",
        "instruction": "Instrucción Oracle de prueba", "expected_technology": "oracle",
    }
    values.update(changes)
    return save_finding(db, **values)


def load(context, **changes):
    values = {
        "company_id": context["company"].id, "execution_id": context["execution"].id,
        "source_id": context["source"].id,
    }
    values.update(changes)
    return interpret_oracle.load_evidence(**values)


def test_loads_only_authorized_oracle_evidence(oracle_contexts):
    first, second = oracle_contexts
    data, status = load(first)
    assert status == "completed"
    assert [row["id"] for row in data] == [first["evidence"].id]
    assert second["evidence"].id not in [row["id"] for row in data]
    assert data[0]["metric_name"] == "oracle_blocked_sessions"
    assert data[0]["profile"] == {"code": "ORACLE_PROFILE", "version": "1"}
    assert data[0]["analysis_status"] == "completed"


@pytest.mark.parametrize("field", ["company_id", "execution_id", "source_id"])
def test_loader_rejects_foreign_context(oracle_contexts, field):
    first, second = oracle_contexts
    value = {"company_id": second["company"].id, "execution_id": second["execution"].id, "source_id": second["source"].id}[field]
    with pytest.raises(ValueError):
        load(first, **{field: value})


def test_loader_rejects_weblogic_source(db_session, oracle_contexts):
    context = oracle_contexts[0]
    technology = db_session.scalar(select(Technology).where(Technology.code == "weblogic"))
    source = Source(company_id=context["company"].id, technology_id=technology.id, code="WL_OTHER", name="WebLogic", source_timezone="America/Santiago")
    db_session.add(source)
    db_session.flush()
    with pytest.raises(ValueError, match="Fuente Oracle"):
        load(context, source_id=source.id)


@pytest.mark.parametrize("status", ["processing", "failed"])
def test_loader_rejects_unavailable_execution(db_session, oracle_contexts, status):
    context = oracle_contexts[0]
    context["execution"].status = status
    db_session.flush()
    with pytest.raises(ValueError, match="no está disponible"):
        load(context)


def test_loader_preserves_partial_coverage_status(db_session, oracle_contexts):
    context = oracle_contexts[0]
    context["execution"].status = "partial"
    db_session.flush()
    data, status = load(context)
    assert status == data[0]["analysis_status"] == "partial"


def test_save_oracle_finding_with_provenance_and_api(client, db_session, oracle_contexts):
    context = oracle_contexts[0]
    finding = persist(db_session, context)
    association = db_session.scalar(select(FindingEvidence).where(FindingEvidence.finding_id == finding.id))
    assert association.evidence_id == context["evidence"].id
    assert finding.prompt_sha256 == hashlib.sha256("Instrucción Oracle de prueba".encode()).hexdigest()
    assert finding.agent_name == "oracle_specialist"
    assert finding.event_context == {}
    assert db_session.scalar(select(FindingEvent.id).where(FindingEvent.finding_id == finding.id)) is None
    response = client.get(f"/api/v1/companies/{context['company'].id}/findings/{finding.id}")
    assert response.status_code == 200
    assert response.json()["evidence_ids"] == [context["evidence"].id]
    assert response.json()["event_ids"] == []
    assert response.json()["event_context"] == {}


def test_save_rejects_foreign_evidence_and_rolls_back(db_session, oracle_contexts):
    first, second = oracle_contexts
    with pytest.raises(FindingPersistenceError) as captured:
        persist(db_session, first, proposal=proposal(first, evidence_ids=[second["evidence"].id]))
    assert captured.value.code == "INVALID_EVIDENCE"
    assert db_session.scalar(select(Finding.id).where(Finding.company_id == first["company"].id)) is None


def test_save_rejects_wrong_source_technology(db_session, oracle_contexts):
    context = oracle_contexts[0]
    with pytest.raises(FindingPersistenceError) as captured:
        persist(db_session, context, expected_technology="weblogic", agent_name="weblogic_specialist")
    assert captured.value.code == "SOURCE_NOT_FOUND"


def test_save_rejects_mismatched_known_agent(db_session, oracle_contexts):
    with pytest.raises(FindingPersistenceError) as captured:
        persist(db_session, oracle_contexts[0], agent_name="weblogic_specialist")
    assert captured.value.code == "INVALID_AGENT_CONTEXT"


def test_save_rejects_oracle_event_citations(db_session, oracle_contexts):
    context = oracle_contexts[0]
    with pytest.raises(FindingPersistenceError) as captured:
        persist(db_session, context, proposal=proposal(context, event_ids=[99]))
    assert captured.value.code == "INVALID_EVENT_CONTEXT"


def test_save_rejects_event_context_for_oracle(db_session, oracle_contexts):
    context = oracle_contexts[0]
    event_context = EventContext(
        company_id=context["company"].id, execution_id=context["execution"].id,
        source_id=context["source"].id, resource_key=context["evidence"].resource_key,
        data_cutoff_at=context["execution"].data_cutoff_at,
        margin_seconds=120, event_limit=100, max_message_chars=2000,
        windows=(EventWindow(evidence_id=context["evidence"].id, start=context["evidence"].start_at, end=context["evidence"].end_at),),
    )
    with pytest.raises(FindingPersistenceError) as captured:
        persist(db_session, context, event_context=event_context)
    assert captured.value.code == "INVALID_EVENT_CONTEXT"


def test_duplicate_is_rejected_by_service_and_preflight(db_session, oracle_contexts):
    context = oracle_contexts[0]
    finding = persist(db_session, context)
    with pytest.raises(ValueError, match=f"hallazgo {finding.id}"):
        interpret_oracle.ensure_can_persist(context["company"].id, context["execution"].id, context["source"].id, context["evidence"].resource_key, "oracle_specialist")
    with pytest.raises(FindingPersistenceError) as captured:
        persist(db_session, context)
    assert captured.value.code == "FINDING_ALREADY_EXISTS"


def test_preflight_does_not_mix_companies(db_session, oracle_contexts):
    first, second = oracle_contexts
    persist(db_session, second)
    interpret_oracle.ensure_can_persist(first["company"].id, first["execution"].id, first["source"].id, first["evidence"].resource_key, "oracle_specialist")
