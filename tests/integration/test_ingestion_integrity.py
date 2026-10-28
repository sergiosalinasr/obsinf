from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.company import Company
from app.models.ingestion import (
    IngestionBatch,
    IngestionError,
    IngestionFile,
)
from app.models.source import Source
from app.models.technology import Technology


@pytest.fixture
def ingestion_context(db_session):
    """Prepara dos empresas, cada una con su propia fuente."""
    technology = db_session.scalar(
        select(Technology).where(Technology.code == "weblogic")
    )
    assert technology is not None

    companies = []
    sources = []

    for index in range(2):
        company = Company(
            code=f"TEST_{uuid4().hex[:12]}",
            name=f"Empresa de prueba {index}",
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
        db_session.add(source)
        db_session.flush()

        companies.append(company)
        sources.append(source)

    return companies, sources


def make_batch(company_id, source_id, **changes):
    """Construye un lote válido sin guardarlo todavía."""
    values = {
        "company_id": company_id,
        "source_id": source_id,
        "idempotency_key": uuid4().hex,
        "request_fingerprint": "a" * 64,
        "request_manifest": {"files": []},
        "requested_by": "pytest",
    }
    values.update(changes)

    return IngestionBatch(**values)


def make_file(batch, **changes):
    """Construye los metadatos de un archivo perteneciente al lote."""
    values = {
        "company_id": batch.company_id,
        "batch_id": batch.id,
        "original_filename": "metrics.jsonl",
        "storage_key": (
            f"companies/{batch.company_id}/raw/{uuid4().hex}.jsonl"
        ),
        "sha256": "b" * 64,
        "size_bytes": 100,
    }
    values.update(changes)

    return IngestionFile(**values)


def assert_rejected(db_session, record, expected_sqlstate):
    """Comprueba el tipo de rechazo y conserva utilizable la sesión.

    El SAVEPOINT aísla la inserción inválida de los datos preparados
    por la fixture y de la transacción externa de la prueba.
    """
    with pytest.raises(IntegrityError) as captured:
        with db_session.begin_nested():
            db_session.add(record)
            db_session.flush()

    assert captured.value.orig.sqlstate == expected_sqlstate


def test_valid_ingestion_chain(db_session, ingestion_context):
    """Permite guardar un lote, su archivo y un error del mismo archivo."""
    companies, sources = ingestion_context

    batch = make_batch(companies[0].id, sources[0].id)
    db_session.add(batch)
    db_session.flush()

    file = make_file(batch)
    db_session.add(file)
    db_session.flush()

    error = IngestionError(
        company_id=batch.company_id,
        batch_id=batch.id,
        file_id=file.id,
        record_locator="line:3",
        error_code="INVALID_JSON",
        message="El registro no contiene JSON válido",
    )
    db_session.add(error)
    db_session.flush()

    assert batch.id is not None
    assert file.id is not None
    assert error.id is not None
    assert batch.status == "pending"
    assert batch.attempt_count == 0
    assert batch.records_read == 0
    assert file.status == "received"


def test_batch_rejects_source_from_other_company(
    db_session, ingestion_context
):
    """Una empresa no puede cargar un lote en una fuente ajena."""
    companies, sources = ingestion_context

    batch = make_batch(companies[0].id, sources[1].id)

    # 23503: violación de clave foránea.
    assert_rejected(db_session, batch, "23503")


def test_file_rejects_batch_from_other_company(
    db_session, ingestion_context
):
    """El archivo debe pertenecer a la empresa de su lote."""
    companies, sources = ingestion_context

    batch = make_batch(companies[0].id, sources[0].id)
    db_session.add(batch)
    db_session.flush()

    file = make_file(batch, company_id=companies[1].id)

    assert_rejected(db_session, file, "23503")


def test_error_rejects_file_from_other_batch(
    db_session, ingestion_context
):
    """Incluso dentro de una empresa, archivo y error deben usar el mismo lote."""
    companies, sources = ingestion_context

    first = make_batch(companies[0].id, sources[0].id)
    second = make_batch(companies[0].id, sources[0].id)
    db_session.add_all([first, second])
    db_session.flush()

    file = make_file(first)
    db_session.add(file)
    db_session.flush()

    error = IngestionError(
        company_id=companies[0].id,
        batch_id=second.id,
        file_id=file.id,
        error_code="INVALID_RECORD",
        message="Error de prueba",
    )

    assert_rejected(db_session, error, "23503")


def test_error_without_file_is_allowed(db_session, ingestion_context):
    """Permite errores generales del lote sin archivo asociado."""
    companies, sources = ingestion_context

    batch = make_batch(companies[0].id, sources[0].id)
    db_session.add(batch)
    db_session.flush()

    error = IngestionError(
        company_id=batch.company_id,
        batch_id=batch.id,
        error_code="PROCESSING_FAILED",
        message="No fue posible completar el procesamiento",
    )
    db_session.add(error)
    db_session.flush()

    assert error.id is not None
    assert error.file_id is None


def test_duplicate_idempotency_key_is_rejected(
    db_session, ingestion_context
):
    """Impide repetir una clave dentro de la misma empresa y fuente."""
    companies, sources = ingestion_context
    key = uuid4().hex

    first = make_batch(
        companies[0].id,
        sources[0].id,
        idempotency_key=key,
    )
    db_session.add(first)
    db_session.flush()

    duplicate = make_batch(
        companies[0].id,
        sources[0].id,
        idempotency_key=key,
    )

    # 23505: violación de unicidad.
    assert_rejected(db_session, duplicate, "23505")


def test_idempotency_key_can_repeat_for_another_source(
    db_session, ingestion_context
):
    """La misma clave puede usarse en otra fuente de la misma empresa."""
    companies, sources = ingestion_context

    other_source = Source(
        company_id=companies[0].id,
        technology_id=sources[0].technology_id,
        code="WL_OTHER",
        name="Otra fuente",
        source_timezone="America/Santiago",
    )
    db_session.add(other_source)
    db_session.flush()

    key = uuid4().hex

    batches = [
        make_batch(
            companies[0].id, source.id, idempotency_key=key
        )
        for source in (sources[0], other_source)
    ]
    db_session.add_all(batches)
    db_session.flush()

    assert batches[0].id != batches[1].id


def test_idempotency_key_can_repeat_for_another_company(
    db_session, ingestion_context
):
    """La clave de una empresa no bloquea las cargas de otra."""
    companies, sources = ingestion_context
    key = uuid4().hex

    batches = [
        make_batch(
            company.id, source.id, idempotency_key=key
        )
        for company, source in zip(companies, sources)
    ]
    db_session.add_all(batches)
    db_session.flush()

    assert batches[0].id != batches[1].id


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "invalid"},
        {"attempt_count": -1},
        {"records_read": -1},
        {"records_accepted": -1},
        {"records_rejected": -1},
        {"records_duplicate": -1},
    ],
)
def test_invalid_batch_values(
    db_session, ingestion_context, changes
):
    """Rechaza estados desconocidos y contadores negativos."""
    companies, sources = ingestion_context

    batch = make_batch(
        companies[0].id,
        sources[0].id,
        **changes,
    )

    # 23514: violación de una restricción CHECK.
    assert_rejected(db_session, batch, "23514")


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "invalid"},
        {"size_bytes": -1},
    ],
)
def test_invalid_file_values(
    db_session, ingestion_context, changes
):
    """Rechaza estados de archivo inválidos y tamaños negativos."""
    companies, sources = ingestion_context

    batch = make_batch(companies[0].id, sources[0].id)
    db_session.add(batch)
    db_session.flush()

    file = make_file(batch, **changes)

    assert_rejected(db_session, file, "23514")