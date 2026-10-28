import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.analysis.finding_contract import FindingProposal
from app.models.analysis import AnalysisExecution, Evidence
from app.models.company import Company
from app.models.finding import Finding, FindingEvidence
from app.models.normality import NormalityProfile, NormalityRule
from app.models.source import Source
from app.models.technology import Technology
from app.services.findings import FindingPersistenceError, save_finding


@pytest.fixture
def service_context(db_session):
    """Prepara dos empresas y una evidencia para cada una."""
    technology = db_session.scalar(
        select(Technology).where(Technology.code == "weblogic")
    )
    assert technology is not None

    start = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    contexts = []

    for index in range(2):
        company = Company(
            code=f"TEST_{uuid4().hex[:12]}",
            name=f"Empresa {index}",
        )
        db_session.add(company)
        db_session.flush()

        source = Source(
            company_id=company.id,
            technology_id=technology.id,
            code="WL_TEST",
            name="WebLogic de prueba",
            source_timezone="America/Santiago",
        )
        profile = NormalityProfile(
            company_id=company.id,
            code="PROFILE",
            version="1",
            name="Perfil",
        )
        db_session.add_all([source, profile])
        db_session.flush()

        rule = NormalityRule(
            company_id=company.id,
            profile_id=profile.id,
            source_id=source.id,
            resource_key="ManagedServer1",
            metric_name="jdbc_active_connections",
            unit="count",
            dimensions={},
            series_key="{}",
            upper_threshold=55,
            max_gap_seconds=90,
        )
        execution = AnalysisExecution(
            company_id=company.id,
            profile_id=profile.id,
            profile_code=profile.code,
            profile_version=profile.version,
            detector_version="baseline_deviation:1.0.0",
            period_start=start,
            period_end=start + timedelta(hours=1),
            data_cutoff_at=start + timedelta(hours=2),
            status="completed",
        )
        db_session.add_all([rule, execution])
        db_session.flush()

        evidence = Evidence(
            company_id=company.id,
            execution_id=execution.id,
            rule_id=rule.id,
            source_id=source.id,
            evidence_type="BASELINE_DEVIATION",
            resource_key="ManagedServer1",
            metric_name="jdbc_active_connections",
            unit="count",
            series_key="{}",
            comparison="above_upper_threshold",
            threshold_value=55,
            min_observed=58,
            max_observed=62,
            start_at=start + timedelta(minutes=2),
            end_at=start + timedelta(minutes=3),
            duration_seconds=60,
            sample_count=2,
        )
        db_session.add(evidence)
        db_session.flush()

        contexts.append({
            "company": company,
            "source": source,
            "execution": execution,
            "evidence": evidence,
        })

    return contexts


def proposal_for(evidence_id, **changes):
    """Construye una propuesta válida para las evidencias preparadas."""
    values = {
        "resource_key": "ManagedServer1",
        "start": "2026-10-27T12:02:00Z",
        "end": "2026-10-27T12:03:00Z",
        "classification": "ANOMALY",
        "severity": "LOW",
        "confidence": 0.75,
        "finding": "Se observó una desviación del rango configurado.",
        "evidence_ids": [evidence_id],
        "possible_implications": [],
    }
    values.update(changes)

    return FindingProposal.model_validate(values)


def persist(db_session, context, proposal, **changes):
    """Ejecuta el servicio con metadatos de prueba."""
    values = {
        "company_id": context["company"].id,
        "execution_id": context["execution"].id,
        "source_id": context["source"].id,
        "proposal": proposal,
        "agent_name": "weblogic_specialist",
        "model_name": "openai/gpt-5-mini",
        "instruction": "Instrucción de prueba",
    }
    values.update(changes)

    return save_finding(db_session, **values)


def test_save_finding_with_evidence(db_session, service_context):
    """Guarda el hallazgo, su procedencia y la asociación."""
    context = service_context[0]
    evidence = context["evidence"]

    finding = persist(
        db_session, context, proposal_for(evidence.id)
    )

    association = db_session.scalar(
        select(FindingEvidence).where(
            FindingEvidence.company_id == context["company"].id,
            FindingEvidence.finding_id == finding.id,
        )
    )

    assert finding.classification == "ANOMALY"
    assert finding.model_name == "openai/gpt-5-mini"
    assert finding.prompt_sha256 == hashlib.sha256(
        "Instrucción de prueba".encode("utf-8")
    ).hexdigest()
    assert association.evidence_id == evidence.id


def test_rejects_evidence_from_other_company(
    db_session, service_context
):
    """No guarda una propuesta que cite evidencia ajena."""
    first, second = service_context

    with pytest.raises(FindingPersistenceError) as captured:
        persist(
            db_session,
            first,
            proposal_for(second["evidence"].id),
        )

    assert captured.value.code == "INVALID_EVIDENCE"

    saved = db_session.scalar(
        select(Finding.id).where(
            Finding.company_id == first["company"].id,
            Finding.execution_id == first["execution"].id,
        )
    )
    assert saved is None


def test_rejects_period_not_covering_evidence(
    db_session, service_context
):
    """Rechaza el hallazgo si su período no cubre la evidencia."""
    context = service_context[0]
    proposal = proposal_for(
        context["evidence"].id,
        end="2026-10-27T12:02:30Z",
    )

    with pytest.raises(FindingPersistenceError) as captured:
        persist(db_session, context, proposal)

    assert captured.value.code == "INVALID_PROPOSAL"


def test_rejects_duplicate_finding(db_session, service_context):
    """El mismo agente no guarda dos hallazgos para el mismo contexto."""
    context = service_context[0]
    proposal = proposal_for(context["evidence"].id)

    persist(db_session, context, proposal)

    with pytest.raises(FindingPersistenceError) as captured:
        persist(db_session, context, proposal)

    assert captured.value.code == "FINDING_ALREADY_EXISTS"


def test_rejects_unfinished_execution(db_session, service_context):
    """Solo interpreta ejecuciones completadas o parciales."""
    context = service_context[0]
    context["execution"].status = "processing"
    db_session.flush()

    with pytest.raises(FindingPersistenceError) as captured:
        persist(
            db_session,
            context,
            proposal_for(context["evidence"].id),
        )

    assert captured.value.code == "ANALYSIS_NOT_READY"