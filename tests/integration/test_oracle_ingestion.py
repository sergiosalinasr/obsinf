"""Fuentes Oracle, recepción y procesamiento con aislamiento por empresa."""

import json
from copy import deepcopy
from datetime import timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.company import Company
from app.models.ingestion import IngestionBatch, IngestionError
from app.models.observations import MetricNormalized
from app.models.source import Source
from app.models.technology import Technology
from app.services import ingestions, ingestion_processing


def source_payload(technology_id, **changes):
    payload = {
        "technology_id": technology_id, "code": "ORACLE_ERP_DEMO",
        "name": "Oracle ERP de demostración", "environment": "production",
        "ingestion_method": "file", "source_timezone": "America/Santiago",
    }
    payload.update(changes)
    return payload


@pytest.fixture
def oracle_context(client, db_session, tmp_path, monkeypatch):
    """Obtiene el catálogo migrado y crea la fuente usando la API real."""
    technology = db_session.scalar(select(Technology).where(Technology.code == "oracle"))
    assert technology is not None, "Aplicar la migración seed oracle technology en obsinf_test"
    company = Company(code=f"TEST_{uuid4().hex[:12]}", name="Empresa Oracle")
    other = Company(code=f"TEST_{uuid4().hex[:12]}", name="Otra empresa")
    db_session.add_all([company, other])
    db_session.flush()
    response = client.post(
        f"/api/v1/companies/{company.id}/sources", json=source_payload(technology.id)
    )
    assert response.status_code == 201, response.text
    source = db_session.get(Source, response.json()["id"])
    settings = get_settings().model_copy(update={"data_dir": tmp_path})
    monkeypatch.setattr(ingestions, "get_settings", lambda: settings)
    monkeypatch.setattr(ingestion_processing, "get_settings", lambda: settings)
    return {
        "company": company, "other_company": other, "technology": technology,
        "source": source, "root": tmp_path,
    }


def metric(name="oracle_active_sessions", value=20, **changes):
    payload = {
        "timestamp": "2026-10-27T09:02:00-03:00",
        "resource_key": "ORCLPDB1/ERP_SERVICE", "metric_name": name,
        "value": value, "unit": "count", "attributes": {},
    }
    payload.update(changes)
    return payload


def content(*records):
    return ("\n".join(json.dumps(row) for row in records) + "\n").encode("utf-8")


def upload(client, context, *, key="oracle-001", records=None, formats=None, company_id=None):
    if records is None:
        records = [content(metric(), metric("oracle_blocked_sessions", 3))]
    if formats is None:
        formats = ["obsinf_metrics_jsonl_v1"] * len(records)
    manifest = {"files": [{"position": i, "format": name} for i, name in enumerate(formats)]}
    return client.post(
        f"/api/v1/companies/{company_id or context['company'].id}/sources/{context['source'].id}/ingestions",
        headers={"Idempotency-Key": key}, data={"manifest": json.dumps(manifest)},
        files=[("files", (f"oracle_{i}.jsonl", data, "application/octet-stream")) for i, data in enumerate(records)],
    )


def metrics_for(db, context):
    return list(db.scalars(select(MetricNormalized).where(
        MetricNormalized.company_id == context["company"].id,
        MetricNormalized.source_id == context["source"].id,
    ).order_by(MetricNormalized.id)).all())


def assert_nothing_saved(db, context):
    assert db.scalar(select(IngestionBatch.id).where(
        IngestionBatch.company_id == context["company"].id,
        IngestionBatch.source_id == context["source"].id,
    )) is None
    assert not any(path.is_file() for path in context["root"].rglob("*"))


def test_register_oracle_source_and_read_it(client, oracle_context):
    context = oracle_context
    response = client.get(f"/api/v1/companies/{context['company'].id}/sources/{context['source'].id}")
    assert response.status_code == 200
    assert response.json()["technology_id"] == context["technology"].id
    assert response.json()["code"] == "ORACLE_ERP_DEMO"


@pytest.mark.parametrize("entity", ["company", "technology"])
def test_registration_rejects_inactive_oracle_origin(client, db_session, oracle_context, entity):
    context = oracle_context
    context[entity].is_active = False
    db_session.flush()
    response = client.post(
        f"/api/v1/companies/{context['company'].id}/sources",
        json=source_payload(context["technology"].id, code="ORACLE_OTHER"),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == ("COMPANY_INACTIVE" if entity == "company" else "TECHNOLOGY_INACTIVE")


def test_upload_and_process_oracle_metrics(client, db_session, oracle_context):
    context = oracle_context
    response = upload(client, context)
    assert response.status_code == 202, response.text
    result = ingestion_processing.process_batch(db_session, context["company"].id, response.json()["batch_id"])
    assert result["status"] == "completed"
    assert result["records_read"] == result["records_accepted"] == 2
    assert result["records_rejected"] == result["records_duplicate"] == 0
    rows = metrics_for(db_session, context)
    assert {row.metric_name for row in rows} == {"oracle_active_sessions", "oracle_blocked_sessions"}
    assert all(row.resource_key == "ORCLPDB1/ERP_SERVICE" and row.file_id is not None for row in rows)
    assert all(row.observed_at.astimezone(timezone.utc).hour == 12 for row in rows)
    status = client.get(response.json()["status_url"])
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["parser_version"] == "obsinf_metrics_jsonl_v1:1.1.0"


def test_oracle_repeated_request_is_idempotent(client, db_session, oracle_context):
    first = upload(client, oracle_context)
    second = upload(client, oracle_context)
    assert first.status_code == second.status_code == 202
    assert first.json()["batch_id"] == second.json()["batch_id"]
    assert len([p for p in oracle_context["root"].rglob("*") if p.is_file()]) == 1


def test_oracle_deduplicates_metrics_in_different_batches(client, db_session, oracle_context):
    results = []
    for key in ("oracle-first", "oracle-second"):
        response = upload(client, oracle_context, key=key)
        assert response.status_code == 202
        results.append(ingestion_processing.process_batch(db_session, oracle_context["company"].id, response.json()["batch_id"]))
    assert results[0]["records_accepted"] == 2
    assert results[1]["records_duplicate"] == 2
    assert results[1]["records_accepted"] == 0
    assert len(metrics_for(db_session, oracle_context)) == 2


def test_oracle_upload_rejects_other_company(client, db_session, oracle_context):
    response = upload(client, oracle_context, company_id=oracle_context["other_company"].id)
    assert response.status_code == 404
    assert_nothing_saved(db_session, oracle_context)


@pytest.mark.parametrize("entity,code", [
    ("company", "INACTIVE_ORIGIN"), ("source", "INACTIVE_ORIGIN"),
    ("technology", "INGESTION_NOT_SUPPORTED"),
])
def test_oracle_upload_rejects_inactive_origin(client, db_session, oracle_context, entity, code):
    oracle_context[entity].is_active = False
    db_session.flush()
    response = upload(client, oracle_context)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
    assert_nothing_saved(db_session, oracle_context)


@pytest.mark.parametrize("mixed", [False, True])
def test_oracle_rejects_weblogic_log_format_atomically(client, db_session, oracle_context, mixed):
    records, formats = [b"not important\n"], ["weblogic_log_v1"]
    if mixed:
        records.insert(0, content(metric()))
        formats.insert(0, "obsinf_metrics_jsonl_v1")
    response = upload(client, oracle_context, records=records, formats=formats)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "FORMAT_NOT_SUPPORTED_FOR_TECHNOLOGY"
    assert_nothing_saved(db_session, oracle_context)


def test_processor_revalidates_stored_format(client, db_session, oracle_context):
    context = oracle_context
    response = upload(client, context)
    batch = db_session.get(IngestionBatch, response.json()["batch_id"])
    manifest = deepcopy(batch.request_manifest)
    manifest["files"][0]["format"] = "weblogic_log_v1"
    batch.request_manifest = manifest
    db_session.flush()
    with pytest.raises(ingestion_processing.ProcessingError):
        ingestion_processing.process_batch(db_session, context["company"].id, batch.id)
    db_session.refresh(batch)
    assert batch.status == "failed"
    assert metrics_for(db_session, context) == []


@pytest.mark.parametrize("metric_name", ["jdbc_active_connections", "cpu_usage_percent"])
def test_oracle_rejects_metrics_from_other_technology(client, db_session, oracle_context, metric_name):
    row = metric(metric_name, unit="count" if metric_name == "jdbc_active_connections" else "percent")
    response = upload(client, oracle_context, records=[content(row)])
    result = ingestion_processing.process_batch(db_session, oracle_context["company"].id, response.json()["batch_id"])
    assert result["status"] == "failed"
    assert result["records_rejected"] == 1
    error = db_session.scalar(select(IngestionError).where(IngestionError.batch_id == result["batch_id"]))
    assert error.error_code == "METRIC_NOT_SUPPORTED_FOR_TECHNOLOGY"


def test_oracle_keeps_valid_records_and_reports_wrong_metric(client, db_session, oracle_context):
    response = upload(client, oracle_context, records=[content(metric(), metric("jdbc_active_connections"))])
    result = ingestion_processing.process_batch(db_session, oracle_context["company"].id, response.json()["batch_id"])
    assert result["status"] == "partial"
    assert result["records_accepted"] == result["records_rejected"] == 1
    error = db_session.scalar(select(IngestionError).where(IngestionError.batch_id == result["batch_id"]))
    assert error.record_locator == "line:2"


@pytest.mark.parametrize("value", [-1, 1.5, True, "20"])
def test_oracle_invalid_count_is_record_error(client, db_session, oracle_context, value):
    response = upload(client, oracle_context, records=[content(metric(value=value))])
    result = ingestion_processing.process_batch(db_session, oracle_context["company"].id, response.json()["batch_id"])
    assert result["status"] == "failed"
    assert result["records_accepted"] == 0
    error = db_session.scalar(select(IngestionError).where(IngestionError.batch_id == result["batch_id"]))
    assert error.error_code == "INVALID_METRIC"


def test_weblogic_rejects_oracle_metric(client, db_session, oracle_context):
    context = oracle_context
    weblogic = db_session.scalar(select(Technology).where(Technology.code == "weblogic"))
    response = client.post(
        f"/api/v1/companies/{context['company'].id}/sources",
        json=source_payload(weblogic.id, code="WL_REGRESSION"),
    )
    assert response.status_code == 201
    wl_context = {**context, "source": db_session.get(Source, response.json()["id"])}
    response = upload(client, wl_context)
    result = ingestion_processing.process_batch(db_session, context["company"].id, response.json()["batch_id"])
    assert result["status"] == "failed"
    assert result["records_rejected"] == 2
    assert metrics_for(db_session, wl_context) == []


def test_oracle_processing_rejects_other_company(client, db_session, oracle_context):
    response = upload(client, oracle_context)
    batch_id = response.json()["batch_id"]
    with pytest.raises(ingestion_processing.ProcessingError):
        ingestion_processing.process_batch(db_session, oracle_context["other_company"].id, batch_id)
    assert db_session.get(IngestionBatch, batch_id).status == "pending"
    assert metrics_for(db_session, oracle_context) == []
