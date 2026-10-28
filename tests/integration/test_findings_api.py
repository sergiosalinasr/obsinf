"""Pruebas PostgreSQL de consulta, paginación y aislamiento de hallazgos."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.dependencies import require_local_dev
from app.main import app
from app.models.analysis import AnalysisExecution, Evidence
from app.models.company import Company
from app.models.finding import Finding, FindingEvidence
from app.models.normality import NormalityProfile, NormalityRule
from app.models.source import Source
from app.models.technology import Technology


@pytest.fixture
def finding_query_context(db_session):
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


@pytest.fixture
def saved_findings(db_session, finding_query_context):
    """Guarda tres interpretaciones por empresa sin llamadas a OpenAI."""
    for context in finding_query_context:
        evidence = context["evidence"]
        rows = []
        for index, (classification, severity) in enumerate([
            ("ANOMALY", "LOW"), ("RISK", "HIGH"), ("EVENT", "INFO")
        ]):
            finding = Finding(
                company_id=context["company"].id,
                execution_id=context["execution"].id,
                source_id=context["source"].id,
                resource_key=evidence.resource_key,
                start_at=evidence.start_at,
                end_at=evidence.end_at,
                classification=classification,
                severity=severity,
                confidence=0.75,
                finding=f"Interpretación de prueba {index}",
                possible_implications=["Hipótesis pendiente de validación"],
                agent_name=f"test_agent_{index}",
                model_name="test-model",
                prompt_sha256="a" * 64,
            )
            db_session.add(finding)
            db_session.flush()
            db_session.add(FindingEvidence(
                company_id=context["company"].id,
                finding_id=finding.id,
                evidence_id=evidence.id,
            ))
            rows.append(finding)
        context["findings"] = rows
    db_session.flush()
    return finding_query_context


def base_url(context):
    return f"/api/v1/companies/{context['company'].id}/findings"


def test_list_findings_is_scoped_to_company(client, saved_findings):
    first, second = saved_findings
    response = client.get(base_url(first))
    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body["items"]] == [
        row.id for row in first["findings"]
    ]
    assert all(row["company_id"] == first["company"].id for row in body["items"])
    assert not {row["id"] for row in body["items"]} & {
        row.id for row in second["findings"]
    }
    assert body["next_after_id"] is None


def test_get_finding_with_provenance_and_evidence(client, saved_findings):
    context = saved_findings[0]
    finding = context["findings"][0]
    response = client.get(f"{base_url(context)}/{finding.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == finding.id
    assert body["execution_id"] == context["execution"].id
    assert body["source_id"] == context["source"].id
    assert body["resource_key"] == "ManagedServer1"
    assert body["classification"] == "ANOMALY"
    assert body["severity"] == "LOW"
    assert body["confidence"] == 0.75
    assert body["finding"] == finding.finding
    assert body["possible_implications"] == finding.possible_implications
    assert body["agent_name"] == finding.agent_name
    assert body["model_name"] == "test-model"
    assert body["prompt_sha256"] == "a" * 64
    assert body["evidence_ids"] == [context["evidence"].id]
    assert body["start_at"] and body["end_at"] and body["created_at"]


def test_list_includes_evidence_ids(client, saved_findings):
    context = saved_findings[0]
    body = client.get(base_url(context)).json()
    assert all(
        row["evidence_ids"] == [context["evidence"].id]
        for row in body["items"]
    )


def test_pagination_has_no_repeated_or_missing_findings(client, saved_findings):
    context = saved_findings[0]
    expected = [row.id for row in context["findings"]]
    ids, after_id = [], 0
    for position in range(3):
        response = client.get(base_url(context), params={"limit": 1, "after_id": after_id})
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        ids.append(body["items"][0]["id"])
        if position < 2:
            assert body["next_after_id"] == expected[position]
            after_id = body["next_after_id"]
        else:
            assert body["next_after_id"] is None
    assert ids == expected


def test_exact_page_size_does_not_advertise_another_page(client, saved_findings):
    response = client.get(base_url(saved_findings[0]), params={"limit": 3})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 3
    assert response.json()["next_after_id"] is None


def test_cursor_after_last_finding_returns_empty_page(client, saved_findings):
    context = saved_findings[0]
    response = client.get(base_url(context), params={"after_id": context["findings"][-1].id})
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_after_id": None}


@pytest.mark.parametrize("field", [
    "execution_id", "source_id", "resource_key", "classification", "severity"
])
def test_each_filter(client, saved_findings, field):
    context = saved_findings[0]
    finding = context["findings"][0]
    value = getattr(finding, field)
    response = client.get(base_url(context), params={field: value})
    assert response.status_code == 200
    items = response.json()["items"]
    expected = [row.id for row in context["findings"] if getattr(row, field) == value]
    assert [item["id"] for item in items] == expected


def test_combined_filters_are_applied_together(client, saved_findings):
    context = saved_findings[0]
    finding = context["findings"][1]
    params = {
        field: getattr(finding, field)
        for field in ["execution_id", "source_id", "resource_key", "classification", "severity"]
    }
    response = client.get(base_url(context), params=params)
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["items"]] == [finding.id]
    params["severity"] = "LOW"
    assert client.get(base_url(context), params=params).json()["items"] == []


@pytest.mark.parametrize("field", ["execution_id", "source_id"])
def test_foreign_filters_do_not_leak_findings(client, saved_findings, field):
    first, second = saved_findings
    foreign_id = getattr(second["findings"][0], field)
    response = client.get(base_url(first), params={field: foreign_id})
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_after_id": None}


def test_resource_filter_without_matches(client, saved_findings):
    response = client.get(base_url(saved_findings[0]), params={"resource_key": "OtherServer"})
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_after_id": None}


def test_foreign_and_missing_finding_have_identical_response(client, saved_findings):
    first, second = saved_findings
    foreign = client.get(f"{base_url(first)}/{second['findings'][0].id}")
    # Un ID negativo reservado para la prueba no sirve: sería un 422.
    # Se usa el máximo BIGINT, inexistente en la base de pruebas.
    missing = client.get(f"{base_url(first)}/9223372036854775807")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {
        "detail": {"code": "FINDING_NOT_FOUND", "message": "Hallazgo no encontrado"}
    }


def test_list_missing_company(client):
    response = client.get("/api/v1/companies/9223372036854775807/findings")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "COMPANY_NOT_FOUND"


def test_existing_company_without_findings(client, finding_query_context):
    response = client.get(base_url(finding_query_context[0]))
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_after_id": None}


def test_inactive_company_can_consult_historical_findings(client, db_session, saved_findings):
    context = saved_findings[0]
    context["company"].is_active = False
    db_session.flush()
    response = client.get(base_url(context))
    assert response.status_code == 200
    assert len(response.json()["items"]) == 3


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": 1001}, {"after_id": 9223372036854775808}, {"after_id": -1}, {"after_id": "invalid"},
    {"execution_id": 0}, {"source_id": -1}, {"resource_key": ""},
    {"resource_key": "x" * 501}, {"classification": "UNKNOWN"},
    {"severity": "UNKNOWN"}, {"severity": "low"},
])
def test_invalid_query_returns_422(client, saved_findings, params):
    response = client.get(base_url(saved_findings[0]), params=params)
    assert response.status_code == 422


@pytest.mark.parametrize("path", [
    "/api/v1/companies/0/findings",
    "/api/v1/companies/9223372036854775808/findings",
    "/api/v1/companies/1/findings/0",
    "/api/v1/companies/1/findings/invalid",
])
def test_invalid_path_returns_422(client, path):
    assert client.get(path).status_code == 422


@pytest.mark.parametrize("detail", [False, True])
def test_both_routes_keep_local_access_guard(client, saved_findings, detail):
    """Comprueba que ambos endpoints ejecutan la dependencia de acceso."""
    context = saved_findings[0]
    path = base_url(context)
    if detail:
        path += f"/{context['findings'][0].id}"

    def deny_access():
        raise HTTPException(status_code=403, detail="Acceso no habilitado")

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[require_local_dev] = deny_access
    try:
        assert client.get(path).status_code == 403
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
