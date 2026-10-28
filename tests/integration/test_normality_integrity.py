from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.company import Company
from app.models.normality import NormalityProfile, NormalityRule
from app.models.source import Source
from app.models.technology import Technology


@pytest.fixture
def normality_context(db_session):
    """Prepara dos empresas, con una fuente y perfil por empresa."""
    technology = db_session.scalar(
        select(Technology).where(Technology.code == "weblogic")
    )
    assert technology is not None

    companies = []
    sources = []
    profiles = []

    for index in range(2):
        company = Company(
            code=f"TEST_{uuid4().hex[:12]}",
            name=f"Empresa de normalidad {index}",
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
            name="Normalidad de prueba",
        )
        db_session.add_all([source, profile])
        db_session.flush()

        companies.append(company)
        sources.append(source)
        profiles.append(profile)

    return {
        "companies": companies,
        "sources": sources,
        "profiles": profiles,
    }


def make_rule(context, **changes):
    """Construye una regla válida de conexiones activas."""
    values = {
        "company_id": context["companies"][0].id,
        "profile_id": context["profiles"][0].id,
        "source_id": context["sources"][0].id,
        "resource_key": "ManagedServer1",
        "metric_name": "jdbc_active_connections",
        "unit": "count",
        "dimensions": {},
        "series_key": "{}",
        "lower_threshold": 20,
        "upper_threshold": 55,
        "min_samples": 1,
        "max_gap_seconds": 90,
    }
    values.update(changes)
    return NormalityRule(**values)


def assert_rejected(db_session, record, expected_sqlstate):
    """Aísla el rechazo para mantener utilizable la sesión."""
    with pytest.raises(IntegrityError) as captured:
        with db_session.begin_nested():
            db_session.add(record)
            db_session.flush()

    assert captured.value.orig.sqlstate == expected_sqlstate


def test_valid_profile_and_rule(db_session, normality_context):
    """Comprueba valores predeterminados y fechas de PostgreSQL."""
    profile = normality_context["profiles"][0]
    rule = make_rule(normality_context)

    db_session.add(rule)
    db_session.flush()

    assert profile.status == "draft"
    assert profile.profile_type == "CONFIGURED"
    assert profile.created_at is not None
    assert profile.updated_at is not None

    assert rule.id is not None
    assert rule.created_at is not None
    assert rule.dimensions == {}
    assert rule.series_key == "{}"


def test_same_profile_identity_in_different_companies(
    normality_context,
):
    """La misma combinación código/versión es válida en otra empresa."""
    first, second = normality_context["profiles"]

    assert first.code == second.code
    assert first.version == second.version
    assert first.company_id != second.company_id


def test_duplicate_profile_version(db_session, normality_context):
    """Rechaza código y versión duplicados dentro de una empresa."""
    original = normality_context["profiles"][0]

    duplicate = NormalityProfile(
        company_id=original.company_id,
        code=original.code,
        version=original.version,
        name="Perfil duplicado",
    )

    assert_rejected(db_session, duplicate, "23505")


def test_multiple_draft_versions_are_allowed(
    db_session, normality_context
):
    """Permite preparar versiones distintas del mismo perfil."""
    original = normality_context["profiles"][0]

    next_version = NormalityProfile(
        company_id=original.company_id,
        code=original.code,
        version="2.0",
        name="Nueva versión",
    )
    db_session.add(next_version)
    db_session.flush()

    assert next_version.id != original.id
    assert next_version.status == "draft"


def test_only_one_active_version(db_session, normality_context):
    """El índice parcial impide activar dos versiones del mismo código."""
    original = normality_context["profiles"][0]
    original.status = "active"
    db_session.flush()

    conflicting = NormalityProfile(
        company_id=original.company_id,
        code=original.code,
        version="2.0",
        name="Segunda versión activa",
        status="active",
    )

    assert_rejected(db_session, conflicting, "23505")


def test_active_profile_is_scoped_to_company(
    db_session, normality_context
):
    """Dos empresas pueden activar el mismo código de perfil."""
    for profile in normality_context["profiles"]:
        profile.status = "active"

    db_session.flush()

    assert all(
        profile.status == "active"
        for profile in normality_context["profiles"]
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"code": "   "},
        {"version": ""},
        {"name": ""},
        {"profile_type": "HISTORICAL"},
        {"status": "unknown"},
    ],
)
def test_invalid_profile_values(
    db_session, normality_context, changes
):
    """Comprueba restricciones de textos, tipo y estado."""
    values = {
        "company_id": normality_context["companies"][0].id,
        "code": f"PROFILE_{uuid4().hex[:12]}",
        "version": "1.0",
        "name": "Perfil inválido de prueba",
    }
    values.update(changes)

    assert_rejected(
        db_session,
        NormalityProfile(**values),
        "23514",
    )


@pytest.mark.parametrize("reference", ["profile", "source"])
def test_rule_rejects_other_company(
    db_session, normality_context, reference
):
    """Una regla no puede utilizar un perfil o fuente de otra empresa."""
    changes = (
        {"profile_id": normality_context["profiles"][1].id}
        if reference == "profile"
        else {"source_id": normality_context["sources"][1].id}
    )

    assert_rejected(
        db_session,
        make_rule(normality_context, **changes),
        "23503",
    )


def test_duplicate_rule_series(db_session, normality_context):
    """Rechaza dos reglas para la misma serie dentro del perfil."""
    db_session.add(make_rule(normality_context))
    db_session.flush()

    assert_rejected(
        db_session,
        make_rule(normality_context, upper_threshold=60),
        "23505",
    )


def test_same_rule_in_another_profile(
    db_session, normality_context
):
    """Una nueva versión puede definir la misma serie."""
    original = normality_context["profiles"][0]

    next_profile = NormalityProfile(
        company_id=original.company_id,
        code=original.code,
        version="2.0",
        name="Nueva versión",
    )
    db_session.add(next_profile)
    db_session.flush()

    first = make_rule(normality_context)
    second = make_rule(
        normality_context,
        profile_id=next_profile.id,
        upper_threshold=60,
    )
    db_session.add_all([first, second])
    db_session.flush()

    assert first.id != second.id


def test_distinct_dimensions_are_allowed(
    db_session, normality_context
):
    """Dos series dimensionales distintas pueden tener reglas propias."""
    first = make_rule(
        normality_context,
        dimensions={"pool": "ERP"},
        series_key='{"pool":"ERP"}',
    )
    second = make_rule(
        normality_context,
        dimensions={"pool": "REPORTS"},
        series_key='{"pool":"REPORTS"}',
    )
    db_session.add_all([first, second])
    db_session.flush()

    assert first.id != second.id


@pytest.mark.parametrize(
    "lower,upper",
    [
        (None, 55),
        (20, None),
        (0, 0),
    ],
)
def test_valid_threshold_combinations(
    db_session, normality_context, lower, upper
):
    """Admite límites unilaterales y valores esperados exactos."""
    rule = make_rule(
        normality_context,
        lower_threshold=lower,
        upper_threshold=upper,
    )
    db_session.add(rule)
    db_session.flush()

    assert rule.id is not None


@pytest.mark.parametrize(
    "changes",
    [
        {"lower_threshold": None, "upper_threshold": None},
        {"lower_threshold": 60, "upper_threshold": 55},
        {"lower_threshold": float("nan")},
        {"lower_threshold": float("-inf")},
        {"upper_threshold": float("nan")},
        {"upper_threshold": float("inf")},
        {"min_samples": 0},
        {"min_samples": -1},
        {"max_gap_seconds": 0},
        {"max_gap_seconds": -1},
        {"max_gap_seconds": float("inf")},
        {"max_gap_seconds": float("nan")},
        {"resource_key": "   "},
        {"metric_name": ""},
        {"unit": ""},
        {"series_key": ""},
        {"dimensions": []},
    ],
)
def test_invalid_rule_values(
    db_session, normality_context, changes
):
    """PostgreSQL rechaza configuraciones fuera del contrato."""
    assert_rejected(
        db_session,
        make_rule(normality_context, **changes),
        "23514",
    )

def profile_payload(version="1.0"):
    """Datos de una versión de prueba."""
    from app.schemas.normality import ProfileCreate

    return ProfileCreate(
        code="SERVICE-PROFILE",
        version=version,
        name="Perfil de servicio",
    )


def rule_payload(source_id, **changes):
    """Datos de una regla de prueba."""
    from app.schemas.normality import RuleCreate

    values = {
        "source_id": source_id,
        "resource_key": "ManagedServer1",
        "metric_name": "jdbc_active_connections",
        "unit": "count",
        "lower_threshold": 20,
        "upper_threshold": 55,
        "min_samples": 2,
        "max_gap_seconds": 90,
    }
    values.update(changes)
    return RuleCreate(**values)


def test_service_creates_profile_and_rule(
    db_session, normality_context
):
    from app.services.normality import create_profile, create_rule

    company = normality_context["companies"][0]
    source = normality_context["sources"][0]

    profile = create_profile(db_session, company.id, profile_payload())
    rule = create_rule(
        db_session, company.id, profile.id, rule_payload(source.id)
    )

    assert profile.status == "draft"
    assert rule.company_id == company.id
    assert rule.dimensions == {}
    assert rule.series_key == "{}"


def test_service_rejects_duplicate_profile(
    db_session, normality_context
):
    from app.services.normality import NormalityError, create_profile

    company = normality_context["companies"][0]

    create_profile(db_session, company.id, profile_payload())

    with pytest.raises(NormalityError) as captured:
        create_profile(db_session, company.id, profile_payload())

    assert captured.value.code == "PROFILE_VERSION_EXISTS"


def test_service_rejects_duplicate_rule(
    db_session, normality_context
):
    from app.services.normality import (
        NormalityError,
        create_profile,
        create_rule,
    )

    company = normality_context["companies"][0]
    source = normality_context["sources"][0]
    profile = create_profile(db_session, company.id, profile_payload())

    create_rule(db_session, company.id, profile.id, rule_payload(source.id))

    with pytest.raises(NormalityError) as captured:
        create_rule(
            db_session, company.id, profile.id, rule_payload(source.id)
        )

    assert captured.value.code == "RULE_ALREADY_EXISTS"


def test_service_rejects_foreign_source(
    db_session, normality_context
):
    from app.services.normality import (
        NormalityError,
        create_profile,
        create_rule,
    )

    company = normality_context["companies"][0]
    other_source = normality_context["sources"][1]
    profile = create_profile(db_session, company.id, profile_payload())

    with pytest.raises(NormalityError) as captured:
        create_rule(
            db_session,
            company.id,
            profile.id,
            rule_payload(other_source.id),
        )

    assert captured.value.code == "SOURCE_NOT_FOUND"


def test_service_rejects_nonempty_dimensions(
    db_session, normality_context
):
    from app.services.normality import (
        NormalityError,
        create_profile,
        create_rule,
    )

    company = normality_context["companies"][0]
    source = normality_context["sources"][0]
    profile = create_profile(db_session, company.id, profile_payload())

    with pytest.raises(NormalityError) as captured:
        create_rule(
            db_session,
            company.id,
            profile.id,
            rule_payload(source.id, dimensions={"pool": "ERP"}),
        )

    assert captured.value.code == "DIMENSIONS_NOT_SUPPORTED"


def test_activate_requires_rule(db_session, normality_context):
    from app.services.normality import (
        NormalityError,
        activate_profile,
        create_profile,
    )

    company = normality_context["companies"][0]
    profile = create_profile(db_session, company.id, profile_payload())

    with pytest.raises(NormalityError) as captured:
        activate_profile(db_session, company.id, profile.id)

    assert captured.value.code == "PROFILE_HAS_NO_RULES"

    db_session.refresh(profile)
    assert profile.status == "draft"


def test_activate_replaces_previous_version(
    db_session, normality_context
):
    from app.services.normality import (
        activate_profile,
        create_profile,
        create_rule,
    )

    company = normality_context["companies"][0]
    source = normality_context["sources"][0]

    first = create_profile(db_session, company.id, profile_payload("1.0"))
    create_rule(db_session, company.id, first.id, rule_payload(source.id))
    activate_profile(db_session, company.id, first.id)

    second = create_profile(db_session, company.id, profile_payload("2.0"))
    create_rule(db_session, company.id, second.id, rule_payload(source.id))
    activate_profile(db_session, company.id, second.id)

    db_session.refresh(first)
    db_session.refresh(second)

    assert first.status == "retired"
    assert second.status == "active"


def test_cannot_add_rule_to_published_profile(
    db_session, normality_context
):
    from app.services.normality import (
        NormalityError,
        activate_profile,
        create_profile,
        create_rule,
    )

    company = normality_context["companies"][0]
    source = normality_context["sources"][0]

    profile = create_profile(db_session, company.id, profile_payload())
    create_rule(db_session, company.id, profile.id, rule_payload(source.id))
    activate_profile(db_session, company.id, profile.id)

    with pytest.raises(NormalityError) as captured:
        create_rule(
            db_session,
            company.id,
            profile.id,
            rule_payload(source.id, resource_key="ManagedServer2"),
        )

    assert captured.value.code == "PROFILE_NOT_DRAFT"

def test_normality_api_workflow(client, normality_context):
    """Crea un perfil, agrega una regla, lo consulta y activa."""
    company = normality_context["companies"][0]
    source = normality_context["sources"][0]
    base_url = f"/api/v1/companies/{company.id}/normality-profiles"

    created = client.post(
        base_url,
        json={
            "code": "API-PROFILE",
            "version": "1.0",
            "name": "Perfil de prueba API",
        },
    )
    assert created.status_code == 201, created.text
    profile_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    rule_response = client.post(
        f"{base_url}/{profile_id}/rules",
        json={
            "source_id": source.id,
            "resource_key": "ManagedServer1",
            "metric_name": "jdbc_active_connections",
            "unit": "count",
            "lower_threshold": 20,
            "upper_threshold": 55,
            "min_samples": 2,
            "max_gap_seconds": 90,
        },
    )
    assert rule_response.status_code == 201, rule_response.text
    assert rule_response.json()["series_key"] == "{}"

    detail = client.get(f"{base_url}/{profile_id}")
    assert detail.status_code == 200
    assert len(detail.json()["rules"]) == 1

    activated = client.post(f"{base_url}/{profile_id}/activate")
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"

    # Una versión publicada no recibe nuevas reglas.
    second_rule = client.post(
        f"{base_url}/{profile_id}/rules",
        json={
            "source_id": source.id,
            "resource_key": "ManagedServer2",
            "metric_name": "jdbc_active_connections",
            "unit": "count",
            "upper_threshold": 55,
            "max_gap_seconds": 90,
        },
    )
    assert second_rule.status_code == 409
    assert second_rule.json()["detail"]["code"] == "PROFILE_NOT_DRAFT"


def test_normality_api_company_isolation(client, normality_context):
    """No permite consultar ni modificar un perfil de otra empresa."""
    company, other_company = normality_context["companies"]
    profile = normality_context["profiles"][0]

    response = client.get(
        f"/api/v1/companies/{other_company.id}"
        f"/normality-profiles/{profile.id}"
    )
    assert response.status_code == 404

    response = client.post(
        f"/api/v1/companies/{other_company.id}"
        f"/normality-profiles/{profile.id}/activate"
    )
    assert response.status_code == 404


def test_normality_api_list_profiles(client, normality_context):
    """Lista solo los perfiles de la empresa solicitada."""
    company = normality_context["companies"][0]
    profile = normality_context["profiles"][0]

    response = client.get(
        f"/api/v1/companies/{company.id}/normality-profiles"
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [profile.id]


def test_normality_api_rejects_invalid_rule(client, normality_context):
    """No permite publicar una regla sin límites."""
    company = normality_context["companies"][0]
    source = normality_context["sources"][0]
    profile = normality_context["profiles"][0]

    response = client.post(
        f"/api/v1/companies/{company.id}"
        f"/normality-profiles/{profile.id}/rules",
        json={
            "source_id": source.id,
            "resource_key": "ManagedServer1",
            "metric_name": "jdbc_active_connections",
            "unit": "count",
            "max_gap_seconds": 90,
        },
    )

    assert response.status_code == 422

def test_analyze_profile_with_deviations(
    db_session, normality_context
):
    """Consulta mediciones del perfil y conserva los IDs de evidencia."""
    from datetime import datetime, timedelta, timezone

    from app.models.ingestion import IngestionBatch
    from app.models.observations import MetricNormalized
    from app.schemas.normality import ProfileCreate, RuleCreate
    from app.services.baseline_analysis import analyze_profile
    from app.services.normality import (
        activate_profile,
        create_profile,
        create_rule,
    )

    company = normality_context["companies"][0]
    source = normality_context["sources"][0]

    profile = create_profile(
        db_session,
        company.id,
        ProfileCreate(code="ANALYSIS", version="1", name="Análisis"),
    )

    rule = create_rule(
        db_session,
        company.id,
        profile.id,
        RuleCreate(
            source_id=source.id,
            resource_key="ManagedServer1",
            metric_name="jdbc_active_connections",
            unit="count",
            lower_threshold=20,
            upper_threshold=55,
            max_gap_seconds=90,
        ),
    )
    activate_profile(db_session, company.id, profile.id)

    batch = IngestionBatch(
        company_id=company.id,
        source_id=source.id,
        idempotency_key=uuid4().hex,
        request_fingerprint="a" * 64,
        request_manifest={"files": []},
        requested_by="pytest",
    )
    db_session.add(batch)
    db_session.flush()

    start = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    measurements = []

    for index, value in enumerate([35, 58, 62, 50, 15, 18, 30]):
        measurement = MetricNormalized(
            company_id=company.id,
            source_id=source.id,
            batch_id=batch.id,
            resource_key="ManagedServer1",
            metric_name="jdbc_active_connections",
            value=value,
            unit="count",
            observed_at=start + timedelta(minutes=index),
            attributes={},
            dedup_key=uuid4().hex,
        )
        db_session.add(measurement)
        measurements.append(measurement)

    db_session.flush()

    result = analyze_profile(
        db_session,
        company.id,
        profile.id,
        start,
        start + timedelta(minutes=7),
    )

    assert result["coverage"][0]["rule_id"] == rule.id
    assert result["coverage"][0]["status"] == "analyzed"
    assert result["coverage"][0]["samples"] == 7
    assert len(result["evidence"]) == 2

    assert result["evidence"][0]["comparison"] == "above_upper_threshold"
    assert result["evidence"][0]["metric_ids"] == [
        measurements[1].id,
        measurements[2].id,
    ]

    assert result["evidence"][1]["comparison"] == "below_lower_threshold"
    assert result["evidence"][1]["metric_ids"] == [
        measurements[4].id,
        measurements[5].id,
    ]


def test_analysis_reports_no_compatible_data(
    db_session, normality_context
):
    """No confunde falta de mediciones con operación normal."""
    from datetime import datetime, timedelta, timezone

    from app.schemas.normality import ProfileCreate, RuleCreate
    from app.services.baseline_analysis import analyze_profile
    from app.services.normality import (
        activate_profile,
        create_profile,
        create_rule,
    )

    company = normality_context["companies"][0]
    source = normality_context["sources"][0]

    profile = create_profile(
        db_session,
        company.id,
        ProfileCreate(code="NO-DATA", version="1", name="Sin datos"),
    )
    create_rule(
        db_session,
        company.id,
        profile.id,
        RuleCreate(
            source_id=source.id,
            resource_key="ManagedServer1",
            metric_name="jdbc_active_connections",
            unit="count",
            upper_threshold=55,
            max_gap_seconds=90,
        ),
    )
    activate_profile(db_session, company.id, profile.id)

    start = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    result = analyze_profile(
        db_session, company.id, profile.id, start, start + timedelta(hours=1)
    )

    assert result["coverage"][0]["status"] == "no_compatible_data"
    assert result["evidence"] == []


def test_analysis_rejects_foreign_profile(
    db_session, normality_context
):
    """Una empresa no puede analizar el perfil de otra."""
    from datetime import datetime, timedelta, timezone

    from app.services.baseline_analysis import (
        BaselineAnalysisError,
        analyze_profile,
    )

    other_company = normality_context["companies"][1]
    profile = normality_context["profiles"][0]
    start = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)

    with pytest.raises(BaselineAnalysisError, match="no encontrado"):
        analyze_profile(
            db_session,
            other_company.id,
            profile.id,
            start,
            start + timedelta(hours=1),
        )

@pytest.fixture
def analysis_context(db_session, normality_context):
    """Prepara una ejecución y una medición por empresa."""
    from datetime import datetime, timedelta, timezone

    from app.models.analysis import AnalysisExecution
    from app.models.ingestion import IngestionBatch
    from app.models.observations import MetricNormalized

    start = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)

    executions = []
    metrics = []

    for index in range(2):
        company = normality_context["companies"][index]
        source = normality_context["sources"][index]
        profile = normality_context["profiles"][index]

        batch = IngestionBatch(
            company_id=company.id,
            source_id=source.id,
            idempotency_key=uuid4().hex,
            request_fingerprint="a" * 64,
            request_manifest={"files": []},
            requested_by="pytest",
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
        )
        db_session.add_all([batch, execution])
        db_session.flush()

        metric = MetricNormalized(
            company_id=company.id,
            source_id=source.id,
            batch_id=batch.id,
            resource_key="ManagedServer1",
            metric_name="jdbc_active_connections",
            value=60,
            unit="count",
            observed_at=start + timedelta(minutes=2),
            attributes={},
            dedup_key=uuid4().hex,
        )
        db_session.add(metric)
        db_session.flush()

        executions.append(execution)
        metrics.append(metric)

    # Regla de la primera empresa.
    rule = make_rule(normality_context)
    db_session.add(rule)
    db_session.flush()

    return {
        **normality_context,
        "start": start,
        "executions": executions,
        "metrics": metrics,
        "rule": rule,
    }


def make_execution(context, **changes):
    """Construye otra ejecución válida de la primera empresa."""
    from datetime import timedelta

    from app.models.analysis import AnalysisExecution

    profile = context["profiles"][0]
    start = context["start"]

    values = {
        "company_id": context["companies"][0].id,
        "profile_id": profile.id,
        "profile_code": profile.code,
        "profile_version": profile.version,
        "detector_version": "baseline_deviation:1.0.0",
        "period_start": start,
        "period_end": start + timedelta(hours=1),
        "data_cutoff_at": start + timedelta(hours=2),
    }
    values.update(changes)

    return AnalysisExecution(**values)


def make_evidence(context, **changes):
    """Construye una evidencia válida para la primera ejecución."""
    from app.models.analysis import Evidence

    metric = context["metrics"][0]

    values = {
        "company_id": context["companies"][0].id,
        "execution_id": context["executions"][0].id,
        "rule_id": context["rule"].id,
        "source_id": context["sources"][0].id,
        "evidence_type": "BASELINE_DEVIATION",
        "resource_key": "ManagedServer1",
        "metric_name": "jdbc_active_connections",
        "unit": "count",
        "series_key": "{}",
        "comparison": "above_upper_threshold",
        "threshold_value": 55,
        "min_observed": 60,
        "max_observed": 60,
        "start_at": metric.observed_at,
        "end_at": metric.observed_at,
        "duration_seconds": 0,
        "sample_count": 1,
    }
    values.update(changes)

    return Evidence(**values)


def test_valid_analysis_evidence_and_metric(
    db_session, analysis_context
):
    """Guarda la cadena completa de trazabilidad."""
    from app.models.analysis import EvidenceMetric

    execution = analysis_context["executions"][0]
    metric = analysis_context["metrics"][0]

    evidence = make_evidence(analysis_context)
    db_session.add(evidence)
    db_session.flush()

    association = EvidenceMetric(
        company_id=execution.company_id,
        evidence_id=evidence.id,
        metric_id=metric.id,
    )
    db_session.add(association)
    db_session.flush()

    assert execution.status == "processing"
    assert execution.coverage == []
    assert evidence.id is not None
    assert association.id is not None


def test_execution_rejects_profile_from_other_company(
    db_session, analysis_context
):
    """Una ejecución no puede referenciar el perfil de otra empresa."""
    execution = make_execution(
        analysis_context,
        profile_id=analysis_context["profiles"][1].id,
    )

    assert_rejected(db_session, execution, "23503")


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "unknown"},
        {"period_end": "same_as_start"},
        {"period_end": "before_start"},
    ],
)
def test_invalid_execution_values(
    db_session, analysis_context, changes
):
    """Rechaza estados desconocidos y períodos vacíos o invertidos."""
    from datetime import timedelta

    changes = dict(changes)

    if changes.get("period_end") == "same_as_start":
        changes["period_end"] = analysis_context["start"]

    elif changes.get("period_end") == "before_start":
        changes["period_end"] = (
            analysis_context["start"] - timedelta(seconds=1)
        )

    assert_rejected(
        db_session,
        make_execution(analysis_context, **changes),
        "23514",
    )


@pytest.mark.parametrize(
    "reference",
    ["execution", "source", "rule"],
)
def test_evidence_rejects_other_company_reference(
    db_session, analysis_context, reference
):
    """Las referencias de evidencia deben pertenecer a su empresa."""
    if reference == "execution":
        changes = {
            "execution_id": analysis_context["executions"][1].id
        }

    elif reference == "source":
        changes = {
            "source_id": analysis_context["sources"][1].id
        }

    else:
        # Creamos una regla válida para la segunda empresa.
        other_rule = make_rule(
            analysis_context,
            company_id=analysis_context["companies"][1].id,
            profile_id=analysis_context["profiles"][1].id,
            source_id=analysis_context["sources"][1].id,
        )
        db_session.add(other_rule)
        db_session.flush()

        changes = {"rule_id": other_rule.id}

    assert_rejected(
        db_session,
        make_evidence(analysis_context, **changes),
        "23503",
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"comparison": "invalid"},
        {"sample_count": 0},
        {"duration_seconds": -1},
        {"end_at": "before_start"},
    ],
)
def test_invalid_evidence_values(
    db_session, analysis_context, changes
):
    """Comprueba los CHECK definidos en la tabla evidence."""
    from datetime import timedelta

    changes = dict(changes)

    if changes.get("end_at") == "before_start":
        changes["end_at"] = (
            analysis_context["metrics"][0].observed_at
            - timedelta(seconds=1)
        )

    assert_rejected(
        db_session,
        make_evidence(analysis_context, **changes),
        "23514",
    )


def test_evidence_metric_rejects_other_company(
    db_session, analysis_context
):
    """Una evidencia no puede asociarse a una métrica de otra empresa."""
    from app.models.analysis import EvidenceMetric

    evidence = make_evidence(analysis_context)
    db_session.add(evidence)
    db_session.flush()

    association = EvidenceMetric(
        company_id=analysis_context["companies"][0].id,
        evidence_id=evidence.id,
        metric_id=analysis_context["metrics"][1].id,
    )

    assert_rejected(db_session, association, "23503")


def test_duplicate_evidence_metric_is_rejected(
    db_session, analysis_context
):
    """La misma medición no se asocia dos veces a una evidencia."""
    from app.models.analysis import EvidenceMetric

    evidence = make_evidence(analysis_context)
    db_session.add(evidence)
    db_session.flush()

    values = {
        "company_id": analysis_context["companies"][0].id,
        "evidence_id": evidence.id,
        "metric_id": analysis_context["metrics"][0].id,
    }

    db_session.add(EvidenceMetric(**values))
    db_session.flush()

    assert_rejected(db_session, EvidenceMetric(**values), "23505")

def test_persist_analysis_with_evidence(
    db_session, normality_context
):
    """Guarda ejecución, cobertura, evidencia y referencias a métricas."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models.analysis import AnalysisExecution, Evidence, EvidenceMetric
    from app.models.ingestion import IngestionBatch
    from app.models.observations import MetricNormalized
    from app.schemas.normality import ProfileCreate, RuleCreate
    from app.services.baseline_analysis import run_and_save_analysis
    from app.services.normality import (
        activate_profile,
        create_profile,
        create_rule,
    )

    company = normality_context["companies"][0]
    source = normality_context["sources"][0]

    profile = create_profile(
        db_session,
        company.id,
        ProfileCreate(code="PERSIST", version="1", name="Persistencia"),
    )
    create_rule(
        db_session,
        company.id,
        profile.id,
        RuleCreate(
            source_id=source.id,
            resource_key="ManagedServer1",
            metric_name="jdbc_active_connections",
            unit="count",
            lower_threshold=20,
            upper_threshold=55,
            max_gap_seconds=90,
        ),
    )
    activate_profile(db_session, company.id, profile.id)

    batch = IngestionBatch(
        company_id=company.id,
        source_id=source.id,
        idempotency_key=uuid4().hex,
        request_fingerprint="a" * 64,
        request_manifest={"files": []},
        requested_by="pytest",
    )
    db_session.add(batch)
    db_session.flush()

    start = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    metric = MetricNormalized(
        company_id=company.id,
        source_id=source.id,
        batch_id=batch.id,
        resource_key="ManagedServer1",
        metric_name="jdbc_active_connections",
        value=60,
        unit="count",
        observed_at=start,
        attributes={},
        dedup_key=uuid4().hex,
    )
    db_session.add(metric)
    db_session.flush()

    result = run_and_save_analysis(
        db_session, company.id, profile.id, start, start + timedelta(hours=1)
    )

    execution = db_session.get(
        AnalysisExecution, result["execution_id"]
    )
    assert execution.status == "completed"
    assert execution.coverage[0]["samples"] == 1
    assert execution.data_cutoff_at is not None
    assert execution.finished_at >= execution.started_at

    evidence = db_session.scalar(
        select(Evidence).where(
            Evidence.company_id == company.id,
            Evidence.execution_id == execution.id,
        )
    )
    assert evidence is not None
    assert evidence.comparison == "above_upper_threshold"
    assert evidence.threshold_value == 55

    association = db_session.scalar(
        select(EvidenceMetric).where(
            EvidenceMetric.company_id == company.id,
            EvidenceMetric.evidence_id == evidence.id,
        )
    )
    assert association.metric_id == metric.id


def test_persist_analysis_without_data_is_partial(
    db_session, normality_context
):
    """Guarda la cobertura sin presentar la ausencia de datos como normal."""
    from datetime import datetime, timedelta, timezone

    from app.models.analysis import AnalysisExecution
    from app.schemas.normality import ProfileCreate, RuleCreate
    from app.services.baseline_analysis import run_and_save_analysis
    from app.services.normality import (
        activate_profile,
        create_profile,
        create_rule,
    )

    company = normality_context["companies"][0]
    source = normality_context["sources"][0]

    profile = create_profile(
        db_session,
        company.id,
        ProfileCreate(code="PERSIST-NO-DATA", version="1", name="Sin datos"),
    )
    create_rule(
        db_session,
        company.id,
        profile.id,
        RuleCreate(
            source_id=source.id,
            resource_key="ManagedServer1",
            metric_name="jdbc_active_connections",
            unit="count",
            upper_threshold=55,
            max_gap_seconds=90,
        ),
    )
    activate_profile(db_session, company.id, profile.id)

    start = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    result = run_and_save_analysis(
        db_session, company.id, profile.id, start, start + timedelta(hours=1)
    )

    execution = db_session.get(
        AnalysisExecution, result["execution_id"]
    )
    assert execution.status == "partial"
    assert execution.coverage[0]["status"] == "no_compatible_data"
    assert result["evidence"] == []

def test_get_analysis_by_id(client, analysis_context):
    """Consulta la ejecución y su cobertura."""
    company = analysis_context["companies"][0]
    execution = analysis_context["executions"][0]

    response = client.get(
        f"/api/v1/companies/{company.id}/analyses/{execution.id}"
    )

    assert response.status_code == 200
    data = response.json()

    assert data["id"] == execution.id
    assert data["company_id"] == company.id
    assert data["profile_id"] == execution.profile_id
    assert data["status"] == "processing"
    assert data["coverage"] == []


def test_get_analysis_evidence(client, db_session, analysis_context):
    """Devuelve la evidencia con los IDs de las métricas asociadas."""
    from app.models.analysis import EvidenceMetric

    company = analysis_context["companies"][0]
    execution = analysis_context["executions"][0]
    metric = analysis_context["metrics"][0]

    evidence = make_evidence(analysis_context)
    db_session.add(evidence)
    db_session.flush()

    db_session.add(EvidenceMetric(
        company_id=company.id,
        evidence_id=evidence.id,
        metric_id=metric.id,
    ))
    db_session.flush()

    response = client.get(
        f"/api/v1/companies/{company.id}"
        f"/analyses/{execution.id}/evidence"
    )

    assert response.status_code == 200
    data = response.json()

    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == evidence.id
    assert data["items"][0]["metric_ids"] == [metric.id]
    assert data["next_after_id"] is None


def test_analysis_queries_reject_foreign_company(
    client, analysis_context
):
    """Una empresa no puede consultar una ejecución ajena."""
    other_company = analysis_context["companies"][1]
    execution = analysis_context["executions"][0]

    base_url = (
        f"/api/v1/companies/{other_company.id}"
        f"/analyses/{execution.id}"
    )

    for suffix in ("", "/evidence"):
        response = client.get(base_url + suffix)

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "ANALYSIS_NOT_FOUND"


def test_evidence_pagination(client, db_session, analysis_context):
    """Pagina evidencias sin repetirlas."""
    company = analysis_context["companies"][0]
    execution = analysis_context["executions"][0]

    first = make_evidence(analysis_context)
    second = make_evidence(analysis_context)
    db_session.add_all([first, second])
    db_session.flush()

    url = (
        f"/api/v1/companies/{company.id}"
        f"/analyses/{execution.id}/evidence"
    )

    page_one = client.get(url, params={"limit": 1})
    assert page_one.status_code == 200

    data = page_one.json()
    assert [item["id"] for item in data["items"]] == [first.id]
    assert data["next_after_id"] == first.id

    page_two = client.get(
        url,
        params={"limit": 1, "after_id": data["next_after_id"]},
    )
    assert page_two.status_code == 200

    data = page_two.json()
    assert [item["id"] for item in data["items"]] == [second.id]
    assert data["next_after_id"] is None