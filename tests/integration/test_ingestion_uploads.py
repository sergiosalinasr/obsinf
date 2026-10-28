import hashlib
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.company import Company
from app.models.ingestion import IngestionBatch, IngestionFile
from app.models.source import Source
from app.models.technology import Technology
from app.services import ingestions


METRIC_CONTENT = (
    b'{"timestamp":"2026-10-24T12:00:00Z",'
    b'"resource_key":"ManagedServer1",'
    b'"metric_name":"cpu_usage_percent",'
    b'"value":46.5,"unit":"percent"}\n'
)


@pytest.fixture
def upload_context(db_session, tmp_path, monkeypatch):
    """Prepara una fuente y dirige los archivos a almacenamiento temporal."""
    technology = db_session.scalar(
        select(Technology).where(Technology.code == "weblogic")
    )
    assert technology is not None

    company = Company(
        code=f"TEST_{uuid4().hex[:12]}",
        name="Empresa de cargas",
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
        code="WL_UPLOAD",
        name="Fuente de cargas",
        source_timezone="America/Santiago",
    )
    db_session.add(source)
    db_session.flush()

    # Solo sustituimos la configuración del servicio de recepción.
    # La autenticación local y la sesión de pruebas conservan sus fixtures.
    settings = get_settings().model_copy(
        update={"data_dir": tmp_path}
    )
    monkeypatch.setattr(ingestions, "get_settings", lambda: settings)

    return {
        "company": company,
        "other_company": other_company,
        "source": source,
        "settings": settings,
        "root": tmp_path,
    }


def send_upload(
    client,
    context,
    *,
    key="upload-test-001",
    contents=None,
    manifest=None,
    company_id=None,
):
    """Construye una petición multipart como Swagger o Postman."""
    if contents is None:
        contents = [METRIC_CONTENT]

    if manifest is None:
        manifest = json.dumps({
            "files": [
                {
                    "position": index,
                    "format": "obsinf_metrics_jsonl_v1",
                }
                for index in range(len(contents))
            ]
        })

    if company_id is None:
        company_id = context["company"].id

    return client.post(
        (
            f"/api/v1/companies/{company_id}"
            f"/sources/{context['source'].id}/ingestions"
        ),
        headers={"Idempotency-Key": key},
        data={"manifest": manifest},
        files=[
            (
                "files",
                (
                    f"metrics_{index}.jsonl",
                    content,
                    "application/octet-stream",
                ),
            )
            for index, content in enumerate(contents)
        ],
    )


def source_batches(db_session, context):
    """Consulta únicamente los lotes de la fuente preparada."""
    return list(db_session.scalars(
        select(IngestionBatch).where(
            IngestionBatch.company_id == context["company"].id,
            IngestionBatch.source_id == context["source"].id,
        )
    ).all())


def physical_files(context):
    """Encuentra archivos reales dentro del almacenamiento de la prueba."""
    return [
        path
        for path in context["root"].rglob("*")
        if path.is_file()
    ]


def assert_no_upload_saved(db_session, context):
    """Comprueba que un rechazo no dejó lotes ni archivos físicos."""
    assert source_batches(db_session, context) == []
    assert physical_files(context) == []


def test_upload_preserves_original(client, db_session, upload_context):
    """Guarda el original y sus metadatos sin procesarlo."""
    response = send_upload(client, upload_context)

    assert response.status_code == 202, response.text
    data = response.json()
    assert data["status"] == "pending"

    batch = db_session.get(IngestionBatch, data["batch_id"])
    assert batch.company_id == upload_context["company"].id
    assert batch.source_id == upload_context["source"].id
    assert batch.records_read == 0

    files = list(db_session.scalars(
        select(IngestionFile).where(
            IngestionFile.company_id == batch.company_id,
            IngestionFile.batch_id == batch.id,
        )
    ).all())

    assert len(files) == 1
    file = files[0]
    original = upload_context["root"] / file.storage_key

    assert original.read_bytes() == METRIC_CONTENT
    assert file.sha256 == hashlib.sha256(METRIC_CONTENT).hexdigest()
    assert file.size_bytes == len(METRIC_CONTENT)
    assert file.original_filename == "metrics_0.jsonl"
    assert file.status == "received"

    # La URL devuelta permite consultar inmediatamente el lote.
    status_response = client.get(data["status_url"])
    assert status_response.status_code == 200
    assert status_response.json()["id"] == batch.id


def test_repeated_request_is_idempotent(
    client, db_session, upload_context
):
    """La misma solicitud devuelve el lote existente sin copiar archivos."""
    first = send_upload(client, upload_context)
    second = send_upload(client, upload_context)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["batch_id"] == second.json()["batch_id"]
    assert len(source_batches(db_session, upload_context)) == 1
    assert len(physical_files(upload_context)) == 1


def test_idempotency_conflict(client, db_session, upload_context):
    """La misma clave no puede identificar otro contenido."""
    first = send_upload(client, upload_context)
    assert first.status_code == 202, first.text

    response = send_upload(
        client,
        upload_context,
        contents=[METRIC_CONTENT + b"\n"],
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert len(source_batches(db_session, upload_context)) == 1
    assert len(physical_files(upload_context)) == 1

    # El original anterior permanece intacto.
    assert physical_files(upload_context)[0].read_bytes() == METRIC_CONTENT


def test_upload_multiple_files(client, db_session, upload_context):
    """Conserva todos los archivos y sus posiciones en el manifiesto."""
    response = send_upload(
        client,
        upload_context,
        contents=[METRIC_CONTENT, b"invalid-record\n"],
    )

    assert response.status_code == 202, response.text

    batch = db_session.get(IngestionBatch, response.json()["batch_id"])
    assert len(batch.request_manifest["files"]) == 2
    assert [
        item["position"]
        for item in batch.request_manifest["files"]
    ] == [0, 1]
    assert len(physical_files(upload_context)) == 2

    # Recibir no implica validar todavía el contenido de cada archivo.
    assert batch.status == "pending"


@pytest.mark.parametrize(
    "manifest",
    [
        "not-json",
        '{"files":[]}',
        '{"files":[{"position":0,"format":"unknown"}]}',
        (
            '{"files":['
            '{"position":1,"format":"obsinf_metrics_jsonl_v1"}'
            ']}'
        ),
    ],
)
def test_invalid_manifest(
    client, db_session, upload_context, manifest
):
    """Rechaza manifiestos inválidos antes de guardar originales."""
    response = send_upload(
        client, upload_context, manifest=manifest
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_MANIFEST"
    assert_no_upload_saved(db_session, upload_context)


def test_manifest_file_count_mismatch(
    client, db_session, upload_context
):
    """El manifiesto debe describir exactamente los archivos recibidos."""
    manifest = json.dumps({
        "files": [
            {"position": 0, "format": "obsinf_metrics_jsonl_v1"},
            {"position": 1, "format": "obsinf_metrics_jsonl_v1"},
        ]
    })

    response = send_upload(
        client, upload_context, manifest=manifest
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "MANIFEST_MISMATCH"
    assert_no_upload_saved(db_session, upload_context)


def test_upload_rejects_other_company(
    client, db_session, upload_context
):
    """Impide cargar archivos en una fuente de otra empresa."""
    response = send_upload(
        client,
        upload_context,
        company_id=upload_context["other_company"].id,
    )

    assert response.status_code == 404
    assert_no_upload_saved(db_session, upload_context)


@pytest.mark.parametrize("entity", ["company", "source"])
def test_upload_rejects_inactive_origin(
    client, db_session, upload_context, entity
):
    """Las empresas o fuentes inactivas no reciben nuevas cargas."""
    upload_context[entity].is_active = False
    db_session.flush()

    response = send_upload(client, upload_context)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INACTIVE_ORIGIN"
    assert_no_upload_saved(db_session, upload_context)


@pytest.mark.parametrize(
    "case,expected_code",
    [
        ("count", "TOO_MANY_FILES"),
        ("file_size", "FILE_TOO_LARGE"),
        ("batch_size", "BATCH_TOO_LARGE"),
    ],
)
def test_upload_limits(
    client, db_session, upload_context, case, expected_code
):
    """Aplica límites y elimina los temporales de solicitudes rechazadas."""
    settings = upload_context["settings"]

    if case == "count":
        settings.max_files_per_batch = 1
        contents = [b"first", b"second"]

    elif case == "file_size":
        settings.max_file_size_mb = 1
        contents = [b"x" * (1024 * 1024 + 1)]

    else:
        settings.max_file_size_mb = 1
        settings.max_batch_size_mb = 1

        # Cada archivo cabe, pero la suma supera 1 MiB.
        contents = [
            b"x" * (600 * 1024),
            b"y" * (600 * 1024),
        ]

    response = send_upload(
        client, upload_context, contents=contents
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == expected_code
    assert_no_upload_saved(db_session, upload_context)

def log_content(message="Server started"):
    """Genera un log del perfil admitido, con fecha ISO 8601."""
    return (
        "####<2026-10-24T09:00:00-03:00> <Info> <Server> "
        "<host01> <ManagedServer1> <ExecuteThread: '1'> "
        "<kernel> <> <context-01> <1792843200000> "
        f"<BEA-000360> <{message}>\n"
    ).encode("utf-8")


def send_log(client, context, content, key):
    """Recibe un archivo declarado explícitamente como log WebLogic."""
    manifest = json.dumps({
        "files": [
            {"position": 0, "format": "weblogic_log_v1"}
        ]
    })

    return send_upload(
        client,
        context,
        key=key,
        contents=[content],
        manifest=manifest,
    )


def test_log_upload_and_processing(
    client, db_session, upload_context, monkeypatch
):
    """Comprueba recepción → parser → events_normalized."""
    from app.models.observations import EventNormalized
    from app.services import ingestion_processing

    monkeypatch.setattr(
        ingestion_processing,
        "get_settings",
        lambda: upload_context["settings"],
    )

    content = log_content(
        "Server started\nAdditional diagnostic information"
    )
    response = send_log(
        client, upload_context, content, "log-valid"
    )
    assert response.status_code == 202, response.text

    batch_id = response.json()["batch_id"]
    company_id = upload_context["company"].id

    result = ingestion_processing.process_batch(
        db_session, company_id, batch_id
    )

    assert result["status"] == "completed"
    assert result["records_read"] == 1
    assert result["records_accepted"] == 1

    event = db_session.scalar(
        select(EventNormalized).where(
            EventNormalized.company_id == company_id,
            EventNormalized.batch_id == batch_id,
        )
    )

    assert event is not None
    assert event.severity == "info"
    assert event.resource_key == "ManagedServer1"
    assert event.record_locator == "lines:1-2"
    assert "Additional diagnostic information" in event.message

    file = db_session.scalar(
        select(IngestionFile).where(
            IngestionFile.company_id == company_id,
            IngestionFile.batch_id == batch_id,
        )
    )
    assert file.storage_key.endswith(".log")


def test_log_invalid_record_is_available_via_api(
    client, db_session, upload_context, monkeypatch
):
    """Un registro inválido no impide guardar el siguiente."""
    from app.services import ingestion_processing

    monkeypatch.setattr(
        ingestion_processing,
        "get_settings",
        lambda: upload_context["settings"],
    )

    response = send_log(
        client,
        upload_context,
        b"####<incomplete>\n" + log_content(),
        "log-partial",
    )
    assert response.status_code == 202, response.text

    batch_id = response.json()["batch_id"]
    company_id = upload_context["company"].id

    result = ingestion_processing.process_batch(
        db_session, company_id, batch_id
    )

    assert result["status"] == "partial"
    assert result["records_read"] == 2
    assert result["records_accepted"] == 1
    assert result["records_rejected"] == 1

    errors = client.get(
        f"/api/v1/companies/{company_id}"
        f"/ingestions/{batch_id}/errors"
    )

    assert errors.status_code == 200
    assert errors.json()["items"][0]["error_code"] == "INVALID_LOG_RECORD"


def test_same_log_in_another_batch_is_not_duplicated(
    client, db_session, upload_context, monkeypatch
):
    """Claves de solicitud distintas no duplican los mismos eventos."""
    from app.services import ingestion_processing

    monkeypatch.setattr(
        ingestion_processing,
        "get_settings",
        lambda: upload_context["settings"],
    )

    company_id = upload_context["company"].id
    content = log_content()

    results = []

    for key in ("log-first", "log-second"):
        response = send_log(client, upload_context, content, key)
        assert response.status_code == 202, response.text

        results.append(ingestion_processing.process_batch(
            db_session,
            company_id,
            response.json()["batch_id"],
        ))

    assert results[0]["records_accepted"] == 1
    assert results[1]["records_accepted"] == 0
    assert results[1]["records_duplicate"] == 1
    assert results[1]["status"] == "completed"

def test_mixed_metrics_and_logs(
    client, db_session, upload_context, monkeypatch
):
    """Procesa métricas y logs del mismo lote en sus respectivas tablas."""
    from app.models.observations import EventNormalized, MetricNormalized
    from app.services import ingestion_processing

    monkeypatch.setattr(
        ingestion_processing,
        "get_settings",
        lambda: upload_context["settings"],
    )

    manifest = json.dumps({
        "files": [
            {
                "position": 0,
                "format": "obsinf_metrics_jsonl_v1",
            },
            {
                "position": 1,
                "format": "weblogic_log_v1",
            },
        ]
    })

    # La posición del manifiesto corresponde al orden de los archivos.
    response = send_upload(
        client,
        upload_context,
        key="mixed-upload",
        contents=[METRIC_CONTENT, log_content()],
        manifest=manifest,
    )
    assert response.status_code == 202, response.text

    batch_id = response.json()["batch_id"]
    company_id = upload_context["company"].id

    result = ingestion_processing.process_batch(
        db_session, company_id, batch_id
    )

    assert result["status"] == "completed"
    assert result["records_read"] == 2
    assert result["records_accepted"] == 2
    assert result["records_rejected"] == 0
    assert result["records_duplicate"] == 0

    metrics = list(db_session.scalars(
        select(MetricNormalized).where(
            MetricNormalized.company_id == company_id,
            MetricNormalized.batch_id == batch_id,
        )
    ).all())

    events = list(db_session.scalars(
        select(EventNormalized).where(
            EventNormalized.company_id == company_id,
            EventNormalized.batch_id == batch_id,
        )
    ).all())

    assert len(metrics) == 1
    assert len(events) == 1

    files = list(db_session.scalars(
        select(IngestionFile).where(
            IngestionFile.company_id == company_id,
            IngestionFile.batch_id == batch_id,
        )
    ).all())

    metric_file = next(
        file for file in files
        if file.storage_key.endswith(".jsonl")
    )
    log_file = next(
        file for file in files
        if file.storage_key.endswith(".log")
    )

    assert metrics[0].file_id == metric_file.id
    assert events[0].file_id == log_file.id
    assert all(file.status == "processed" for file in files)

    # El GET debe mostrar ambos parsers y ambos archivos.
    status_response = client.get(response.json()["status_url"])
    assert status_response.status_code == 200

    data = status_response.json()
    assert data["status"] == "completed"
    assert len(data["files"]) == 2
    assert "obsinf_metrics_jsonl_v1:" in data["parser_version"]
    assert "weblogic_log_v1:" in data["parser_version"]