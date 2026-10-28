from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.analysis import AnalysisExecution, Evidence
from app.models.company import Company
from app.models.finding import Finding, FindingEvidence
from app.models.normality import NormalityProfile, NormalityRule
from app.models.source import Source
from app.models.technology import Technology


@pytest.fixture
def finding_context(db_session):
    """Prepara dos empresas con ejecución y evidencia propias."""
    technology = db_session.scalar(
        select(Technology).where(Technology.code == "weblogic")
    )
    assert technology is not None

    start = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    companies = []
    sources = []
    executions = []
    evidence_items = []

    for index in range(2):
        company = Company(
            code=f"TEST_{uuid4().hex[:12]}",
            name=f"Empresa de hallazgos {index}",
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
            code="NORMALITY-TEST",
            version="1.0",
            name="Perfil de prueba",
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
            min_samples=1,
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

        companies.append(company)
        sources.append(source)
        executions.append(execution)
        evidence_items.append(evidence)

    return {
        "start": start,
        "companies": companies,
        "sources": sources,
        "executions": executions,
        "evidence": evidence_items,
    }


def make_finding(context, **changes):
    """Construye un hallazgo válido de la primera empresa."""
    values = {
        "company_id": context["companies"][0].id,
        "execution_id": context["executions"][0].id,
        "source_id": context["sources"][0].id,
        "resource_key": "ManagedServer1",
        "start_at": context["start"] + timedelta(minutes=2),
        "end_at": context["start"] + timedelta(minutes=3),
        "classification": "ANOMALY",
        "severity": "LOW",
        "confidence": 0.75,
        "finding": "Se observaron conexiones fuera del rango configurado.",
        "possible_implications": [],
        "agent_name": "weblogic_specialist",
        "model_name": "openai/gpt-5-mini",
        "prompt_sha256": "a" * 64,
    }
    values.update(changes)

    return Finding(**values)


def assert_rejected(db_session, record, expected_sqlstate):
    """Aísla la inserción inválida usando un SAVEPOINT."""
    with pytest.raises(IntegrityError) as captured:
        with db_session.begin_nested():
            db_session.add(record)
            db_session.flush()

    # 23503 = clave foránea; 23505 = unicidad; 23514 = CHECK.
    assert captured.value.orig.sqlstate == expected_sqlstate


def test_valid_finding_and_evidence(db_session, finding_context):
    """Guarda un hallazgo y su relación con una evidencia."""
    finding = make_finding(finding_context)
    db_session.add(finding)
    db_session.flush()

    association = FindingEvidence(
        company_id=finding.company_id,
        finding_id=finding.id,
        evidence_id=finding_context["evidence"][0].id,
    )
    db_session.add(association)
    db_session.flush()

    assert finding.id is not None
    assert finding.created_at is not None
    assert association.id is not None


@pytest.mark.parametrize("reference", ["execution", "source"])
def test_finding_rejects_other_company_reference(
    db_session, finding_context, reference
):
    """Un hallazgo no puede usar una ejecución o fuente de otra empresa."""
    if reference == "execution":
        changes = {
            "execution_id": finding_context["executions"][1].id
        }
    else:
        changes = {
            "source_id": finding_context["sources"][1].id
        }

    assert_rejected(
        db_session,
        make_finding(finding_context, **changes),
        "23503",
    )


@pytest.mark.parametrize("reference", ["finding", "evidence"])
def test_association_rejects_other_company_reference(
    db_session, finding_context, reference
):
    """La relación no puede apuntar a un hallazgo o evidencia ajena."""
    first = make_finding(finding_context)
    second = make_finding(
        finding_context,
        company_id=finding_context["companies"][1].id,
        execution_id=finding_context["executions"][1].id,
        source_id=finding_context["sources"][1].id,
    )
    db_session.add_all([first, second])
    db_session.flush()

    if reference == "finding":
        finding_id = second.id
        evidence_id = finding_context["evidence"][0].id
    else:
        finding_id = first.id
        evidence_id = finding_context["evidence"][1].id

    association = FindingEvidence(
        company_id=finding_context["companies"][0].id,
        finding_id=finding_id,
        evidence_id=evidence_id,
    )

    assert_rejected(db_session, association, "23503")


def test_duplicate_finding_evidence_is_rejected(
    db_session, finding_context
):
    """La misma evidencia no puede asociarse dos veces al mismo hallazgo."""
    finding = make_finding(finding_context)
    db_session.add(finding)
    db_session.flush()

    values = {
        "company_id": finding.company_id,
        "finding_id": finding.id,
        "evidence_id": finding_context["evidence"][0].id,
    }

    db_session.add(FindingEvidence(**values))
    db_session.flush()

    assert_rejected(
        db_session,
        FindingEvidence(**values),
        "23505",
    )


@pytest.mark.parametrize("confidence", [0, 1])
def test_confidence_boundaries_are_allowed(
    db_session, finding_context, confidence
):
    """Los extremos del intervalo de confianza son válidos."""
    finding = make_finding(
        finding_context,
        confidence=confidence,
    )
    db_session.add(finding)
    db_session.flush()

    assert finding.id is not None


@pytest.mark.parametrize(
    "changes",
    [
        {"classification": "UNKNOWN"},
        {"severity": "EXTREME"},
        {"confidence": -0.1},
        {"confidence": 1.1},
        {"confidence": float("nan")},
        {"confidence": float("inf")},
        {"resource_key": "   "},
        {"finding": ""},
        {"possible_implications": {}},
        {"end_at": "before_start"},
    ],
)
def test_invalid_finding_values(
    db_session, finding_context, changes
):
    """Comprueba los valores cubiertos por restricciones CHECK."""
    changes = dict(changes)

    if changes.get("end_at") == "before_start":
        changes["end_at"] = finding_context["start"]

    assert_rejected(
        db_session,
        make_finding(finding_context, **changes),
        "23514",
    )