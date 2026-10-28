"""Contexto, persistencia, consulta e integridad de eventos citados."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.analysis.finding_contract import FindingProposal
from app.models.analysis import AnalysisExecution, Evidence
from app.models.company import Company
from app.models.finding import Finding, FindingEvidence, FindingEvent
from app.models.ingestion import IngestionBatch
from app.models.normality import NormalityProfile, NormalityRule
from app.models.observations import EventNormalized
from app.models.source import Source
from app.models.technology import Technology
from app.services.event_context import load_event_context
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


@pytest.fixture
def event_setup(db_session, service_context):
    """Crea lotes para insertar eventos con procedencia real en cada empresa."""
    for context in service_context:
        batch = IngestionBatch(
            company_id=context["company"].id, source_id=context["source"].id,
            idempotency_key=uuid4().hex, request_fingerprint="a" * 64,
            request_manifest={"files": []}, requested_by="pytest",
        )
        db_session.add(batch)
        db_session.flush()
        context["batch"] = batch
    return service_context


def add_event(db, context, *, seconds=150, **changes):
    start = context["execution"].period_start
    values = {
        "company_id": context["company"].id,
        "source_id": context["source"].id,
        "batch_id": context["batch"].id,
        "resource_key": "ManagedServer1", "record_type": "log",
        "severity": "warning", "event_code": "SYNTHETIC-JDBC",
        "message": "Evento de prueba", "dedup_key": uuid4().hex,
        "occurred_at": start + timedelta(seconds=seconds),
        "received_at": start + timedelta(hours=1), "attributes": {},
    }
    values.update(changes)
    event = EventNormalized(**values)
    db.add(event)
    db.flush()
    return event


def load_context(db, context, **changes):
    values = {
        "company_id": context["company"].id,
        "execution_id": context["execution"].id,
        "source_id": context["source"].id,
        "resource_key": "ManagedServer1", "evidence_ids": [context["evidence"].id],
    }
    values.update(changes)
    return load_event_context(db, **values)


def test_selects_only_company_source_resource_window_and_cutoff(db_session, event_setup):
    first, second = event_setup
    valid = add_event(db_session, first)
    add_event(db_session, second)
    add_event(db_session, first, resource_key="OtherServer")
    add_event(db_session, first, seconds=301)
    add_event(db_session, first, received_at=first["execution"].data_cutoff_at + timedelta(seconds=1))

    # Otra fuente de la misma empresa tampoco debe mezclarse.
    source = Source(
        company_id=first["company"].id, technology_id=first["source"].technology_id,
        code="WL_OTHER", name="Otra fuente", source_timezone="America/Santiago",
    )
    db_session.add(source)
    db_session.flush()
    batch = IngestionBatch(
        company_id=first["company"].id, source_id=source.id,
        idempotency_key=uuid4().hex, request_fingerprint="b" * 64,
        request_manifest={"files": []}, requested_by="pytest",
    )
    db_session.add(batch)
    db_session.flush()
    add_event(db_session, first, source_id=source.id, batch_id=batch.id)
    context = load_context(db_session, first)
    assert [event.id for event in context.events] == [valid.id]
    assert context.has_more_events is False


def test_window_and_receipt_cutoff_are_inclusive(db_session, event_setup):
    first = event_setup[0]
    lower = add_event(db_session, first, seconds=0)
    upper = add_event(db_session, first, seconds=300, received_at=first["execution"].data_cutoff_at)
    context = load_context(db_session, first)
    assert [row.id for row in context.events] == [lower.id, upper.id]


def test_limits_events_and_messages_deterministically(db_session, event_setup):
    first = event_setup[0]
    later = add_event(db_session, first, seconds=160)
    earlier = add_event(db_session, first, seconds=140, message="ABCDEFGHIJK")
    context = load_context(db_session, first, event_limit=1, max_message_chars=5)
    assert [row.id for row in context.events] == [earlier.id]
    assert context.events[0].message == "ABCDE"
    assert context.events[0].message_truncated is True
    assert context.has_more_events is True
    assert later.id not in [row.id for row in context.events]


def test_exact_event_limit_does_not_indicate_truncation(db_session, event_setup):
    first = event_setup[0]
    add_event(db_session, first)
    assert load_context(db_session, first, event_limit=1).has_more_events is False


def test_no_events_is_valid_context(db_session, event_setup):
    context = load_context(db_session, event_setup[0])
    assert context.events == ()
    assert context.has_more_events is False


def test_separate_windows_do_not_fill_the_gap(db_session, event_setup):
    first = event_setup[0]
    original = first["evidence"]
    later = Evidence(
        company_id=original.company_id, execution_id=original.execution_id,
        rule_id=original.rule_id, source_id=original.source_id,
        evidence_type=original.evidence_type, resource_key=original.resource_key,
        metric_name=original.metric_name, unit=original.unit, series_key="{}",
        comparison=original.comparison, threshold_value=55, min_observed=60,
        max_observed=60, start_at=original.start_at + timedelta(minutes=30),
        end_at=original.end_at + timedelta(minutes=30), duration_seconds=60, sample_count=2,
    )
    db_session.add(later)
    db_session.flush()
    add_event(db_session, first, seconds=900)  # Está en el hueco entre ventanas.
    context = load_context(db_session, first, evidence_ids=[original.id, later.id])
    assert context.events == ()


def test_overlapping_windows_do_not_duplicate_events(db_session, event_setup):
    first = event_setup[0]
    original = first["evidence"]
    later = Evidence(
        company_id=original.company_id, execution_id=original.execution_id,
        rule_id=original.rule_id, source_id=original.source_id,
        evidence_type=original.evidence_type, resource_key=original.resource_key,
        metric_name=original.metric_name, unit=original.unit, series_key="{}",
        comparison=original.comparison, threshold_value=55, min_observed=60,
        max_observed=60, start_at=original.start_at + timedelta(minutes=1),
        end_at=original.end_at + timedelta(minutes=1), duration_seconds=60, sample_count=2,
    )
    db_session.add(later)
    db_session.flush()
    event = add_event(db_session, first)
    context = load_context(db_session, first, evidence_ids=[original.id, later.id])
    assert [row.id for row in context.events] == [event.id]


@pytest.mark.parametrize("field", ["company_id", "execution_id", "source_id", "evidence_ids", "resource_key"])
def test_loader_rejects_foreign_context(db_session, event_setup, field):
    first, second = event_setup
    value = {
        "company_id": second["company"].id, "execution_id": second["execution"].id,
        "source_id": second["source"].id, "evidence_ids": [second["evidence"].id],
        "resource_key": "OtherServer",
    }[field]
    with pytest.raises(ValueError):
        load_context(db_session, first, **{field: value})


@pytest.mark.parametrize("changes", [
    {"event_limit": 0}, {"event_limit": 101}, {"margin_seconds": -1},
    {"margin_seconds": 3601}, {"max_message_chars": 0},
])
def test_loader_rejects_invalid_limits(db_session, event_setup, changes):
    with pytest.raises(ValueError):
        load_context(db_session, event_setup[0], **changes)


def test_save_and_api_return_cited_events_and_context(client, db_session, event_setup):
    first = event_setup[0]
    event = add_event(db_session, first)
    context = load_context(db_session, first)
    finding = persist(db_session, first, proposal_for(first["evidence"].id, event_ids=[event.id]), event_context=context)
    link = db_session.scalar(select(FindingEvent).where(FindingEvent.finding_id == finding.id))
    assert link.event_id == event.id
    url = f"/api/v1/companies/{first['company'].id}/findings"
    detail = client.get(f"{url}/{finding.id}")
    assert detail.status_code == 200
    assert detail.json()["event_ids"] == [event.id]
    assert detail.json()["event_context"] == context.model_dump(mode="json")
    assert client.get(url).json()["items"][0]["event_ids"] == [event.id]


def test_legacy_finding_without_context_keeps_empty_references(client, db_session, event_setup):
    first = event_setup[0]
    finding = persist(db_session, first, proposal_for(first["evidence"].id))
    response = client.get(f"/api/v1/companies/{first['company'].id}/findings/{finding.id}")
    assert response.status_code == 200
    assert response.json()["event_ids"] == []
    assert response.json()["event_context"] == {}


def test_foreign_cited_event_rolls_back_without_finding(db_session, event_setup):
    first, second = event_setup
    foreign = add_event(db_session, second)
    context = load_context(db_session, first)
    with pytest.raises(FindingPersistenceError) as error:
        persist(db_session, first, proposal_for(first["evidence"].id, event_ids=[foreign.id]), event_context=context)
    assert error.value.code == "INVALID_EVENT_CONTEXT"
    assert db_session.scalar(select(Finding.id).where(Finding.company_id == first["company"].id)) is None


def test_cited_event_without_authorized_context_is_rejected(db_session, event_setup):
    first = event_setup[0]
    event = add_event(db_session, first)
    with pytest.raises(FindingPersistenceError) as error:
        persist(db_session, first, proposal_for(first["evidence"].id, event_ids=[event.id]))
    assert error.value.code == "INVALID_EVENT_CONTEXT"


def test_changed_message_after_model_call_is_rejected(db_session, event_setup):
    first = event_setup[0]
    event = add_event(db_session, first)
    context = load_context(db_session, first)
    event.message = "Contenido modificado después de la interpretación"
    db_session.flush()
    with pytest.raises(FindingPersistenceError) as error:
        persist(db_session, first, proposal_for(first["evidence"].id, event_ids=[event.id]), event_context=context)
    assert error.value.code == "INVALID_EVENT_CONTEXT"


def test_context_from_other_execution_is_rejected(db_session, event_setup):
    first, second = event_setup
    context = load_context(db_session, second)
    with pytest.raises(FindingPersistenceError) as error:
        persist(db_session, first, proposal_for(first["evidence"].id), event_context=context)
    assert error.value.code == "INVALID_EVENT_CONTEXT"


def test_event_ids_are_sorted_in_api_and_only_cited_ones_are_linked(client, db_session, event_setup):
    first = event_setup[0]
    events = [add_event(db_session, first, seconds=value) for value in [140, 150, 160]]
    context = load_context(db_session, first)
    finding = persist(db_session, first, proposal_for(first["evidence"].id, event_ids=[events[1].id, events[0].id]), event_context=context)
    response = client.get(f"/api/v1/companies/{first['company'].id}/findings/{finding.id}")
    assert response.json()["event_ids"] == [events[0].id, events[1].id]
    assert len(response.json()["event_context"]["events"]) == 3


def test_database_rejects_duplicate_finding_event(db_session, event_setup):
    first = event_setup[0]
    event = add_event(db_session, first)
    finding = persist(db_session, first, proposal_for(first["evidence"].id, event_ids=[event.id]), event_context=load_context(db_session, first))
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(FindingEvent(company_id=first["company"].id, finding_id=finding.id, event_id=event.id))
            db_session.flush()


@pytest.mark.parametrize("foreign_target", ["finding", "event"])
def test_database_rejects_cross_company_associations(db_session, event_setup, foreign_target):
    first, second = event_setup
    event = add_event(db_session, first)
    foreign_event = add_event(db_session, second)
    local_finding = persist(db_session, first, proposal_for(first["evidence"].id))
    foreign_finding = persist(db_session, second, proposal_for(second["evidence"].id))
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(FindingEvent(
                company_id=first["company"].id,
                finding_id=foreign_finding.id if foreign_target == "finding" else local_finding.id,
                event_id=foreign_event.id if foreign_target == "event" else event.id,
            ))
            db_session.flush()


def test_database_requires_object_context(db_session, event_setup):
    first = event_setup[0]
    finding = persist(db_session, first, proposal_for(first["evidence"].id))
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            finding.event_context = []
            db_session.flush()
