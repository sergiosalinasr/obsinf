from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.company import Company
from app.models.ingestion import IngestionBatch, IngestionFile
from app.models.observations import EventNormalized, MetricNormalized
from app.models.source import Source
from app.models.technology import Technology


@pytest.fixture
def observation_context(db_session):
    """Prepara dos empresas y tres fuentes para probar pertenencia.

    Las dos primeras fuentes pertenecen a la primera empresa.
    La tercera pertenece a otra empresa.
    """
    technology = db_session.scalar(
        select(Technology).where(Technology.code == "weblogic")
    )
    assert technology is not None

    companies = [
        Company(
            code=f"TEST_{uuid4().hex[:12]}",
            name=f"Empresa de observaciones {index}",
        )
        for index in range(2)
    ]
    db_session.add_all(companies)
    db_session.flush()

    sources = []
    batches = []
    files = []

    for index, company in enumerate(
        (companies[0], companies[0], companies[1])
    ):
        source = Source(
            company_id=company.id,
            technology_id=technology.id,
            code=f"WL_{index}",
            name=f"Fuente {index}",
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
            original_filename="observations.jsonl",
            storage_key=f"companies/{company.id}/raw/{uuid4().hex}",
            sha256="b" * 64,
            size_bytes=100,
        )
        db_session.add(file)
        db_session.flush()

        sources.append(source)
        batches.append(batch)
        files.append(file)

    return {
        "companies": companies,
        "sources": sources,
        "batches": batches,
        "files": files,
    }


def make_observation(kind, context, index=0, **changes):
    """Construye una observación válida, permitiendo variar sus campos."""
    batch = context["batches"][index]
    file = context["files"][index]

    values = {
        "company_id": batch.company_id,
        "source_id": batch.source_id,
        "batch_id": batch.id,
        "file_id": file.id,
        "record_locator": "line:1",
        "resource_key": "ManagedServer1",
        "dedup_key": uuid4().hex,
    }

    instant = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)

    if kind == "metric":
        model = MetricNormalized
        values.update({
            "metric_name": "cpu_usage_percent",
            "value": 46.5,
            "unit": "percent",
            "observed_at": instant,
        })
    else:
        model = EventNormalized
        values.update({
            "record_type": "log",
            "severity": "info",
            "event_code": "BEA-000360",
            "message": "Server started",
            "occurred_at": instant,
        })

    values.update(changes)
    return model(**values)


def assert_rejected(db_session, record, expected_sqlstate):
    """Aísla la inserción inválida con un SAVEPOINT."""
    with pytest.raises(IntegrityError) as captured:
        with db_session.begin_nested():
            db_session.add(record)
            db_session.flush()

    assert captured.value.orig.sqlstate == expected_sqlstate


@pytest.mark.parametrize("kind", ["metric", "event"])
def test_valid_observation(db_session, observation_context, kind):
    """Guarda una observación con trazabilidad válida."""
    observation = make_observation(kind, observation_context)
    db_session.add(observation)
    db_session.flush()

    assert observation.id is not None
    assert observation.attributes == {}
    assert observation.received_at is not None


@pytest.mark.parametrize("kind", ["metric", "event"])
@pytest.mark.parametrize("mismatch", ["company", "source", "file"])
def test_rejects_inconsistent_origin(
    db_session, observation_context, kind, mismatch
):
    """Impide mezclar empresas, fuentes o archivos de distintos lotes."""
    if mismatch == "company":
        changes = {
            "company_id": observation_context["companies"][1].id,
        }
    elif mismatch == "source":
        # Fuente distinta, aunque pertenece a la misma empresa.
        changes = {
            "source_id": observation_context["sources"][1].id,
        }
    else:
        # Archivo de otro lote, dentro de la misma empresa.
        changes = {
            "file_id": observation_context["files"][1].id,
        }

    observation = make_observation(
        kind, observation_context, **changes
    )

    # 23503: violación de clave foránea.
    assert_rejected(db_session, observation, "23503")


@pytest.mark.parametrize("kind", ["metric", "event"])
def test_allows_observation_without_file(
    db_session, observation_context, kind
):
    """Admite futuros orígenes API que no tengan un archivo asociado."""
    observation = make_observation(
        kind,
        observation_context,
        file_id=None,
        record_locator=None,
    )
    db_session.add(observation)
    db_session.flush()

    assert observation.id is not None
    assert observation.file_id is None


@pytest.mark.parametrize("kind", ["metric", "event"])
def test_duplicate_dedup_key_is_rejected(
    db_session, observation_context, kind
):
    """La misma fuente no puede repetir una clave de observación."""
    key = uuid4().hex

    first = make_observation(
        kind, observation_context, dedup_key=key
    )
    db_session.add(first)
    db_session.flush()

    duplicate = make_observation(
        kind, observation_context, dedup_key=key
    )

    # 23505: violación de unicidad.
    assert_rejected(db_session, duplicate, "23505")


@pytest.mark.parametrize("kind", ["metric", "event"])
@pytest.mark.parametrize("other_index", [1, 2])
def test_dedup_key_can_repeat_in_another_source(
    db_session, observation_context, kind, other_index
):
    """Permite la misma clave en otra fuente, de esta u otra empresa."""
    key = uuid4().hex

    observations = [
        make_observation(
            kind, observation_context, index=0, dedup_key=key
        ),
        make_observation(
            kind,
            observation_context,
            index=other_index,
            dedup_key=key,
        ),
    ]
    db_session.add_all(observations)
    db_session.flush()

    assert observations[0].id != observations[1].id


@pytest.mark.parametrize(
    "value",
    [float("inf"), float("-inf"), float("nan")],
    ids=["positive_infinity", "negative_infinity", "nan"],
)
def test_rejects_nonfinite_metric(
    db_session, observation_context, value
):
    """PostgreSQL debe rechazar valores que no sean finitos."""
    metric = make_observation(
        "metric", observation_context, value=value
    )

    # 23514: violación de una restricción CHECK.
    assert_rejected(db_session, metric, "23514")


@pytest.mark.parametrize(
    "changes",
    [
        {"record_type": "invalid"},
        {"severity": "invalid"},
    ],
)
def test_rejects_invalid_event_classification(
    db_session, observation_context, changes
):
    """Rechaza tipos y severidades fuera del catálogo permitido."""
    event = make_observation(
        "event", observation_context, **changes
    )

    assert_rejected(db_session, event, "23514")