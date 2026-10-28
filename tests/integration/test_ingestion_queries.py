from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.company import Company
from app.models.ingestion import IngestionBatch, IngestionFile
from app.models.source import Source
from app.models.technology import Technology


@pytest.fixture
def saved_ingestion(db_session):
    """Prepara un lote pendiente con un archivo, sin crear archivos físicos."""
    technology = db_session.scalar(
        select(Technology).where(Technology.code == "weblogic")
    )
    assert technology is not None

    company = Company(
        code=f"TEST_{uuid4().hex[:12]}",
        name="Empresa de consulta de lotes",
    )
    other_company = Company(
        code=f"TEST_{uuid4().hex[:12]}",
        name="Otra empresa",
    )
    db_session.add_all([company, other_company])
    db_session.flush()

    source = Source(
        company_id=company.id,
        technology_id=technology.id,
        code="WL_QUERY",
        name="Fuente de prueba",
        source_timezone="America/Santiago",
    )
    db_session.add(source)
    db_session.flush()

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

    file = IngestionFile(
        company_id=company.id,
        batch_id=batch.id,
        original_filename="metrics.jsonl",
        storage_key=f"companies/{company.id}/raw/{uuid4().hex}",
        sha256="b" * 64,
        size_bytes=276,
    )
    db_session.add(file)
    db_session.flush()

    return company, other_company, batch, file


def test_get_pending_ingestion(client, saved_ingestion):
    """Devuelve estado, contadores y archivo sin exponer datos internos."""
    company, _, batch, file = saved_ingestion

    response = client.get(
        f"/api/v1/companies/{company.id}/ingestions/{batch.id}"
    )

    assert response.status_code == 200, response.text
    data = response.json()

    assert data["id"] == batch.id
    assert data["company_id"] == company.id
    assert data["status"] == "pending"
    assert data["records_read"] == 0
    assert data["attempt_count"] == 0
    assert data["started_at"] is None
    assert data["finished_at"] is None

    assert len(data["files"]) == 1
    assert data["files"][0]["id"] == file.id
    assert data["files"][0]["size_bytes"] == 276
    assert data["files"][0]["status"] == "received"

    assert "processing_token" not in data
    assert "request_manifest" not in data
    assert "storage_key" not in data["files"][0]


def test_rejects_other_company(client, saved_ingestion):
    """Conocer el ID de un lote ajeno no permite consultarlo."""
    _, other_company, batch, _ = saved_ingestion

    response = client.get(
        f"/api/v1/companies/{other_company.id}/ingestions/{batch.id}"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "INGESTION_NOT_FOUND"


def test_missing_ingestion(client, db_session, saved_ingestion):
    """Un lote inexistente devuelve 404."""
    company, _, _, _ = saved_ingestion
    missing_id = 9_000_000_000_000_000_000
    assert db_session.get(IngestionBatch, missing_id) is None

    response = client.get(
        f"/api/v1/companies/{company.id}/ingestions/{missing_id}"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "INGESTION_NOT_FOUND"


def test_inactive_company_can_read_history(
    client, db_session, saved_ingestion
):
    """Desactivar la empresa no elimina su consulta histórica."""
    company, _, batch, _ = saved_ingestion
    company.is_active = False
    db_session.flush()

    response = client.get(
        f"/api/v1/companies/{company.id}/ingestions/{batch.id}"
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "company_id,batch_id",
    [(0, 1), (1, 0), (-1, 1)],
)
def test_invalid_identifiers(client, company_id, batch_id):
    """Rechaza identificadores que no sean positivos."""
    response = client.get(
        f"/api/v1/companies/{company_id}/ingestions/{batch_id}"
    )

    assert response.status_code == 422

def prepare_processing_file(
    db_session, saved_ingestion, tmp_path, monkeypatch, content
):
    """Crea un original temporal con metadatos consistentes."""
    import hashlib

    from app.core.config import get_settings
    from app.services import ingestion_processing

    _, _, batch, file = saved_ingestion

    settings = get_settings().model_copy(
        update={"data_dir": tmp_path}
    )
    monkeypatch.setattr(
        ingestion_processing,
        "get_settings",
        lambda: settings,
    )

    path = tmp_path / "companies" / str(batch.company_id) / "0.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)

    file.storage_key = path.relative_to(tmp_path).as_posix()
    file.size_bytes = len(content)
    file.sha256 = hashlib.sha256(content).hexdigest()

    batch.request_manifest = {
        "files": [
            {"position": 0, "format": "obsinf_metrics_jsonl_v1"}
        ]
    }
    db_session.flush()

    return batch, file, path


def test_process_valid_metrics(
    db_session, saved_ingestion, tmp_path, monkeypatch
):
    """Guarda una métrica y registra correctamente sus contadores."""
    from sqlalchemy import select

    from app.models.observations import MetricNormalized
    from app.services.ingestion_processing import process_batch

    content = (
        b'{"timestamp":"2026-10-24T12:00:00Z",'
        b'"resource_key":"ManagedServer1",'
        b'"metric_name":"cpu_usage_percent",'
        b'"value":46.5,"unit":"percent"}\n'
    )

    batch, file, _ = prepare_processing_file(
        db_session, saved_ingestion, tmp_path, monkeypatch, content
    )

    result = process_batch(db_session, batch.company_id, batch.id)

    assert result["status"] == "completed"
    assert result["records_read"] == 1
    assert result["records_accepted"] == 1

    metric = db_session.scalar(
        select(MetricNormalized).where(
            MetricNormalized.company_id == batch.company_id,
            MetricNormalized.batch_id == batch.id,
        )
    )

    assert metric is not None
    assert metric.value == 46.5
    assert metric.file_id == file.id
    assert metric.record_locator == "line:1"

    db_session.refresh(batch)
    db_session.refresh(file)

    assert batch.attempt_count == 1
    assert batch.processing_token is None
    assert file.status == "processed"


def test_process_partial_metrics(
    db_session, saved_ingestion, tmp_path, monkeypatch
):
    """Conserva registros válidos y localiza los inválidos."""
    from sqlalchemy import select

    from app.models.ingestion import IngestionError
    from app.services.ingestion_processing import process_batch

    content = (
        b'{"timestamp":"2026-10-24T12:00:00Z",'
        b'"resource_key":"ManagedServer1",'
        b'"metric_name":"cpu_usage_percent",'
        b'"value":46.5,"unit":"percent"}\n'
        b'not-json\n'
    )

    batch, file, _ = prepare_processing_file(
        db_session, saved_ingestion, tmp_path, monkeypatch, content
    )

    result = process_batch(db_session, batch.company_id, batch.id)

    assert result["status"] == "partial"
    assert result["records_read"] == 2
    assert result["records_accepted"] == 1
    assert result["records_rejected"] == 1

    error = db_session.scalar(
        select(IngestionError).where(
            IngestionError.company_id == batch.company_id,
            IngestionError.batch_id == batch.id,
        )
    )

    assert error.error_code == "INVALID_JSON"
    assert error.record_locator == "line:2"

    db_session.refresh(file)
    assert file.status == "partial"


def test_process_rejects_changed_original(
    db_session, saved_ingestion, tmp_path, monkeypatch
):
    """Detecta un original alterado después de su recepción."""
    from sqlalchemy import select

    from app.models.observations import MetricNormalized
    from app.services.ingestion_processing import (
        ProcessingError,
        process_batch,
    )

    batch, _, path = prepare_processing_file(
        db_session, saved_ingestion, tmp_path, monkeypatch, b"original\n"
    )
    path.write_bytes(b"modified\n")

    with pytest.raises(ProcessingError, match="hash o tamaño"):
        process_batch(db_session, batch.company_id, batch.id)

    db_session.refresh(batch)
    assert batch.status == "failed"

    metrics = list(db_session.scalars(
        select(MetricNormalized).where(
            MetricNormalized.company_id == batch.company_id,
            MetricNormalized.batch_id == batch.id,
        )
    ))
    assert metrics == []

@pytest.fixture
def saved_metrics(db_session, saved_ingestion):
    """Prepara tres mediciones, dos con el mismo instante."""
    from datetime import datetime, timedelta, timezone

    from app.models.observations import MetricNormalized

    company, other_company, batch, file = saved_ingestion
    start = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)

    metrics = []
    for index, minutes in enumerate((0, 0, 1)):
        metric = MetricNormalized(
            company_id=company.id,
            source_id=batch.source_id,
            batch_id=batch.id,
            file_id=file.id,
            record_locator=f"line:{index + 1}",
            resource_key="ManagedServer1",
            metric_name="cpu_usage_percent",
            value=40 + index,
            unit="percent",
            observed_at=start + timedelta(minutes=minutes),
            dedup_key=uuid4().hex,
        )
        db_session.add(metric)
        metrics.append(metric)

    db_session.flush()
    return company, other_company, batch, metrics


def metric_query_params():
    return {
        "from": "2026-10-24T12:00:00Z",
        "to": "2026-10-24T12:02:00Z",
    }


def test_query_metrics_and_period_boundary(client, saved_metrics):
    """El extremo final del período es exclusivo."""
    company, _, batch, metrics = saved_metrics
    params = {
        **metric_query_params(),
        "source_id": batch.source_id,
        "to": "2026-10-24T12:01:00Z",
    }

    response = client.get(
        f"/api/v1/companies/{company.id}/metrics",
        params=params,
    )

    assert response.status_code == 200, response.text
    data = response.json()

    assert [item["id"] for item in data["items"]] == [
        metric.id for metric in metrics[:2]
    ]
    assert data["next_cursor"] is None


def test_metrics_cursor_pagination(client, saved_metrics):
    """Recorre mediciones con igual instante sin omitirlas ni repetirlas."""
    company, _, _, metrics = saved_metrics
    url = f"/api/v1/companies/{company.id}/metrics"
    params = {**metric_query_params(), "limit": 1}
    found_ids = []

    for _ in range(3):
        response = client.get(url, params=params)
        assert response.status_code == 200, response.text

        data = response.json()
        assert len(data["items"]) == 1
        found_ids.append(data["items"][0]["id"])

        if data["next_cursor"] is None:
            break

        params["cursor"] = data["next_cursor"]

    assert found_ids == [metric.id for metric in metrics]
    assert data["next_cursor"] is None


def test_metrics_isolation(client, saved_metrics):
    """La otra empresa no ve métricas ni puede usar una fuente ajena."""
    _, other_company, batch, _ = saved_metrics
    url = f"/api/v1/companies/{other_company.id}/metrics"

    response = client.get(url, params=metric_query_params())
    assert response.status_code == 200
    assert response.json()["items"] == []

    response = client.get(
        url,
        params={
            **metric_query_params(),
            "source_id": batch.source_id,
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SOURCE_NOT_FOUND"


def test_metrics_filters(client, saved_metrics):
    """Aplica filtros exactos de métrica y recurso."""
    company, _, _, _ = saved_metrics
    url = f"/api/v1/companies/{company.id}/metrics"

    for changes in (
        {"metric_name": "memory_usage_percent"},
        {"resource_key": "OtherServer"},
    ):
        response = client.get(
            url, params={**metric_query_params(), **changes}
        )
        assert response.status_code == 200
        assert response.json()["items"] == []


def test_cursor_rejects_changed_filters(client, saved_metrics):
    """No permite continuar un cursor con filtros distintos."""
    company, _, _, _ = saved_metrics
    url = f"/api/v1/companies/{company.id}/metrics"

    first = client.get(
        url, params={**metric_query_params(), "limit": 1}
    )
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    assert cursor is not None

    response = client.get(
        url,
        params={
            **metric_query_params(),
            "cursor": cursor,
            "metric_name": "cpu_usage_percent",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_CURSOR"


@pytest.mark.parametrize(
    "changes",
    [
        {"from": "2026-10-24T12:00:00"},
        {"to": "2026-10-24T12:00:00Z"},
        {"to": "2026-12-24T12:00:00Z"},
        {"limit": 0},
        {"cursor": "not-a-valid-cursor"},
    ],
)
def test_invalid_metric_query(client, saved_metrics, changes):
    """Rechaza fechas sin zona, ventanas inválidas y cursores incorrectos."""
    company, _, _, _ = saved_metrics

    response = client.get(
        f"/api/v1/companies/{company.id}/metrics",
        params={**metric_query_params(), **changes},
    )

    assert response.status_code == 422

def test_ingestion_errors_empty(client, saved_ingestion):
    """Un lote sin errores devuelve una página vacía."""
    company, _, batch, _ = saved_ingestion

    response = client.get(
        f"/api/v1/companies/{company.id}/ingestions/{batch.id}/errors"
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "next_after_id": None,
    }


def test_ingestion_errors_pagination(
    client, db_session, saved_ingestion
):
    """Consulta errores por páginas sin repetir registros."""
    from app.models.ingestion import IngestionError

    company, _, batch, file = saved_ingestion
    errors = []

    for line in (2, 4):
        error = IngestionError(
            company_id=company.id,
            batch_id=batch.id,
            file_id=file.id,
            record_locator=f"line:{line}",
            error_code="INVALID_JSON",
            message="Registro JSON inválido",
        )
        db_session.add(error)
        errors.append(error)

    db_session.flush()

    url = (
        f"/api/v1/companies/{company.id}"
        f"/ingestions/{batch.id}/errors"
    )

    first = client.get(url, params={"limit": 1})
    assert first.status_code == 200
    data = first.json()

    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == errors[0].id
    assert data["items"][0]["record_locator"] == "line:2"
    assert data["items"][0]["file_id"] == file.id
    assert data["next_after_id"] == errors[0].id

    second = client.get(
        url,
        params={
            "limit": 1,
            "after_id": data["next_after_id"],
        },
    )
    assert second.status_code == 200
    data = second.json()

    assert [item["id"] for item in data["items"]] == [errors[1].id]
    assert data["next_after_id"] is None


def test_ingestion_errors_other_company(client, saved_ingestion):
    """No permite consultar errores de un lote ajeno."""
    _, other_company, batch, _ = saved_ingestion

    response = client.get(
        f"/api/v1/companies/{other_company.id}"
        f"/ingestions/{batch.id}/errors"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "INGESTION_NOT_FOUND"


def test_ingestion_errors_missing_batch(
    client, db_session, saved_ingestion
):
    """Distingue un lote inexistente de un lote existente sin errores."""
    company, _, _, _ = saved_ingestion
    missing_id = 9_000_000_000_000_000_000

    assert db_session.get(IngestionBatch, missing_id) is None

    response = client.get(
        f"/api/v1/companies/{company.id}"
        f"/ingestions/{missing_id}/errors"
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 1001},
        {"after_id": -1},
    ],
)
def test_ingestion_errors_invalid_pagination(
    client, saved_ingestion, params
):
    """Rechaza límites y posiciones de paginación inválidos."""
    company, _, batch, _ = saved_ingestion

    response = client.get(
        f"/api/v1/companies/{company.id}"
        f"/ingestions/{batch.id}/errors",
        params=params,
    )

    assert response.status_code == 422


def test_processed_error_is_available_via_api(
    client, db_session, saved_ingestion, tmp_path, monkeypatch
):
    """Comprueba el recorrido parser → BD → consulta de errores."""
    from app.services.ingestion_processing import process_batch

    batch, file, _ = prepare_processing_file(
        db_session,
        saved_ingestion,
        tmp_path,
        monkeypatch,
        b"not-json\n",
    )

    result = process_batch(db_session, batch.company_id, batch.id)

    assert result["status"] == "failed"
    assert result["records_rejected"] == 1

    response = client.get(
        f"/api/v1/companies/{batch.company_id}"
        f"/ingestions/{batch.id}/errors"
    )

    assert response.status_code == 200
    data = response.json()

    assert len(data["items"]) == 1
    assert data["items"][0]["error_code"] == "INVALID_JSON"
    assert data["items"][0]["record_locator"] == "line:1"
    assert data["items"][0]["file_id"] == file.id

@pytest.fixture
def saved_events(db_session, saved_ingestion):
    """Prepara eventos con diferentes severidades y tiempos."""
    from datetime import datetime, timedelta, timezone

    from app.models.observations import EventNormalized

    company, other_company, batch, file = saved_ingestion
    start = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    events = []

    for index, (minutes, severity) in enumerate(
        [(0, "info"), (0, "error"), (1, "warning")]
    ):
        event = EventNormalized(
            company_id=company.id,
            source_id=batch.source_id,
            batch_id=batch.id,
            file_id=file.id,
            record_locator=f"line:{index + 1}",
            resource_key="ManagedServer1",
            record_type="log",
            severity=severity,
            original_severity=severity.title(),
            event_code=f"BEA-TEST-{index}",
            message=f"Mensaje de prueba {index}",
            occurred_at=start + timedelta(minutes=minutes),
            dedup_key=uuid4().hex,
        )
        db_session.add(event)
        events.append(event)

    db_session.flush()
    return company, other_company, batch, events


def event_query_params():
    return {
        "from": "2026-10-24T12:00:00Z",
        "to": "2026-10-24T12:02:00Z",
    }


def test_query_events_period_boundary(client, saved_events):
    """El inicio se incluye y el fin se excluye."""
    company, _, _, events = saved_events

    response = client.get(
        f"/api/v1/companies/{company.id}/events",
        params={
            **event_query_params(),
            "to": "2026-10-24T12:01:00Z",
        },
    )

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [
        event.id for event in events[:2]
    ]


@pytest.mark.parametrize(
    "filters,expected_indexes",
    [
        ({"severity": "error"}, [1]),
        ({"event_code": "BEA-TEST-2"}, [2]),
        ({"resource_key": "OtherServer"}, []),
        ({"record_type": "event"}, []),
        ({"severity": "info", "event_code": "BEA-TEST-1"}, []),
    ],
)
def test_event_filters(client, saved_events, filters, expected_indexes):
    """Aplica los filtros individualmente y en combinación."""
    company, _, _, events = saved_events

    response = client.get(
        f"/api/v1/companies/{company.id}/events",
        params={**event_query_params(), **filters},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [
        events[index].id for index in expected_indexes
    ]


def test_events_cursor_pagination(client, saved_events):
    """Pagina sin perder eventos que comparten el mismo instante."""
    company, _, _, events = saved_events
    url = f"/api/v1/companies/{company.id}/events"
    params = {**event_query_params(), "limit": 1}
    ids = []

    for _ in range(3):
        response = client.get(url, params=params)
        assert response.status_code == 200, response.text

        data = response.json()
        assert len(data["items"]) == 1
        ids.append(data["items"][0]["id"])

        if data["next_cursor"] is None:
            break

        params["cursor"] = data["next_cursor"]

    assert ids == [event.id for event in events]
    assert data["next_cursor"] is None


def test_events_company_isolation(client, saved_events):
    """No devuelve eventos ni acepta fuentes de otra empresa."""
    _, other_company, batch, _ = saved_events
    url = f"/api/v1/companies/{other_company.id}/events"

    response = client.get(url, params=event_query_params())
    assert response.status_code == 200
    assert response.json()["items"] == []

    response = client.get(
        url,
        params={
            **event_query_params(),
            "source_id": batch.source_id,
        },
    )
    assert response.status_code == 404


def test_event_cursor_rejects_changed_filters(client, saved_events):
    """El cursor debe reutilizarse con los mismos filtros."""
    company, _, _, _ = saved_events
    url = f"/api/v1/companies/{company.id}/events"

    first = client.get(
        url, params={**event_query_params(), "limit": 1}
    )
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    assert cursor is not None

    response = client.get(
        url,
        params={
            **event_query_params(),
            "severity": "error",
            "cursor": cursor,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_CURSOR"


@pytest.mark.parametrize(
    "changes",
    [
        {"from": "2026-10-24T12:00:00"},
        {"to": "2026-10-24T12:00:00Z"},
        {"to": "2026-12-24T12:00:00Z"},
        {"severity": "invalid"},
        {"record_type": "invalid"},
        {"limit": 0},
        {"cursor": "invalid-cursor"},
    ],
)
def test_invalid_event_query(client, saved_events, changes):
    """Valida fechas, clasificaciones y paginación."""
    company, _, _, _ = saved_events

    response = client.get(
        f"/api/v1/companies/{company.id}/events",
        params={**event_query_params(), **changes},
    )

    assert response.status_code == 422

def test_processing_operational_dates(
    db_session, saved_ingestion, tmp_path, monkeypatch
):
    """Comprueba que recepción y procesamiento mantienen su orden temporal."""
    from app.services.ingestion_processing import process_batch

    content = (
        b'{"timestamp":"2026-10-24T12:00:00Z",'
        b'"resource_key":"ManagedServer1",'
        b'"metric_name":"cpu_usage_percent",'
        b'"value":46.5,"unit":"percent"}\n'
    )

    batch, file, _ = prepare_processing_file(
        db_session,
        saved_ingestion,
        tmp_path,
        monkeypatch,
        content,
    )

    result = process_batch(db_session, batch.company_id, batch.id)

    assert result["status"] == "completed"

    db_session.refresh(batch)
    db_session.refresh(file)

    assert (
        batch.received_at
        <= batch.started_at
        <= file.processed_at
        <= batch.finished_at
    )
    assert file.received_at <= file.processed_at
    assert batch.heartbeat_at == batch.finished_at