import hashlib
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.capabilities import supports_format, supports_metric, supports_technology
from app.integrations.common.metrics_jsonl import (
    PARSER_VERSION as METRICS_PARSER_VERSION,
    ParseError,
    parse_metrics_jsonl,
)
from app.integrations.weblogic.log_parser import (
    PARSER_VERSION as LOG_PARSER_VERSION,
    LogParseError,
    parse_weblogic_log,
)
from app.models.observations import EventNormalized, MetricNormalized
from app.models.company import Company
from app.models.ingestion import (
    IngestionBatch,
    IngestionError,
    IngestionFile,
)
from app.models.source import Source
from app.models.technology import Technology


class ProcessingError(Exception):
    """Indica que el lote no puede procesarse."""


def database_now(db: Session) -> datetime:
    """Obtiene la hora actual del servidor PostgreSQL.

    clock_timestamp() avanza durante la transacción.
    now() devuelve el instante de inicio de la transacción.
    """
    return db.scalar(select(func.clock_timestamp()))


def resolve_original(root: Path, storage_key: str) -> Path:
    """Impide acceder a archivos fuera de la raíz configurada."""
    root = root.resolve()
    candidate = (root / storage_key).resolve()

    if not candidate.is_relative_to(root):
        raise ProcessingError("Ruta de almacenamiento inválida")

    return candidate


def verify_original(path: Path, file: IngestionFile) -> None:
    """Verifica tamaño y hash antes de interpretar el contenido."""
    digest = hashlib.sha256()
    size = 0

    with path.open("rb") as original:
        while chunk := original.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)

    if size != file.size_bytes or digest.hexdigest() != file.sha256:
        raise ProcessingError("El archivo no coincide con su hash o tamaño")


def claim_batch(db: Session, company_id: int, batch_id: int) -> str:
    """Reclama un lote pendiente y confirma su propiedad."""
    try:
        # Mantenemos el orden empresa → fuente → lote para los bloqueos.
        company = db.scalar(
            select(Company)
            .where(Company.id == company_id)
            .with_for_update()
        )

        batch = db.scalar(
            select(IngestionBatch).where(
                IngestionBatch.id == batch_id,
                IngestionBatch.company_id == company_id,
            )
        )

        if company is None or batch is None:
            raise ProcessingError("Lote no encontrado en la empresa")

        source = db.scalar(
            select(Source)
            .where(
                Source.id == batch.source_id,
                Source.company_id == company_id,
            )
            .with_for_update()
        )

        technology = (
            db.get(Technology, source.technology_id)
            if source is not None else None
        )

        if (
            not company.is_active
            or source is None
            or not source.is_active
            or source.ingestion_method != "file"
            or technology is None
            or not technology.is_active
            or not supports_technology(technology.code)
        ):
            raise ProcessingError("La empresa o fuente no está habilitada")

        batch = db.scalar(
            select(IngestionBatch)
            .where(
                IngestionBatch.id == batch_id,
                IngestionBatch.company_id == company_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        if batch.status != "pending":
            raise ProcessingError(
                f"El lote debe estar pending; estado actual: {batch.status}"
            )

        token = uuid4().hex
        batch.processing_token = token
        batch.status = "processing"
        batch.attempt_count += 1
        batch.started_at = database_now(db)
        batch.heartbeat_at = batch.started_at
        batch.finished_at = None
        batch.error_summary = None

        db.commit()
        return token

    except Exception:
        db.rollback()
        raise

def normalized_records(original, file, format_name, technology_code="weblogic"):
    """Entrega errores o valores listos para insertar según la tecnología.

    El valor predeterminado conserva llamadas anteriores del helper. El
    procesador siempre envía la tecnología obtenida de la fuente autorizada.
    """
    if not supports_format(technology_code, format_name):
        raise ProcessingError("Formato no habilitado para la tecnología de la fuente")
    if format_name == "obsinf_metrics_jsonl_v1":
        for result in parse_metrics_jsonl(original):
            if isinstance(result, ParseError):
                yield result
                continue

            metric = result.metric
            if not supports_metric(technology_code, metric.metric_name):
                yield ParseError(
                    result.line_number,
                    "METRIC_NOT_SUPPORTED_FOR_TECHNOLOGY",
                    "La métrica no está habilitada para la tecnología de la fuente",
                )
                continue

            yield (
                MetricNormalized,
                {
                    "record_locator": result.record_locator,
                    "resource_key": metric.resource_key,
                    "metric_name": metric.metric_name,
                    "value": metric.value,
                    "unit": metric.unit,
                    "observed_at": metric.timestamp,
                    "attributes": metric.attributes,
                    "dedup_key": result.dedup_key,
                },
            )

    elif format_name == "weblogic_log_v1":
        for result in parse_weblogic_log(original, file.sha256):
            if isinstance(result, LogParseError):
                yield result
                continue

            yield (
                EventNormalized,
                {
                    "record_locator": result.record_locator,
                    "resource_key": result.resource_key,
                    "record_type": result.record_type,
                    "severity": result.severity,
                    "original_severity": result.original_severity,
                    "event_code": result.event_code,
                    "message": result.message,
                    "occurred_at": result.occurred_at,
                    "attributes": result.attributes,
                    "dedup_key": result.dedup_key,
                },
            )

    else:
        raise ProcessingError("Formato de archivo no soportado")

def process_batch(
    db: Session,
    company_id: int,
    batch_id: int,
) -> dict:
    """Procesa un lote y guarda observaciones, errores y resultado."""
    token = claim_batch(db, company_id, batch_id)

    try:
        # Este bloqueo protege todas las escrituras del procesamiento.
        # Una recuperación futura deberá adquirir el mismo bloqueo.
        batch = db.scalar(
            select(IngestionBatch)
            .where(
                IngestionBatch.id == batch_id,
                IngestionBatch.company_id == company_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        if batch.processing_token != token or batch.status != "processing":
            raise ProcessingError("Se perdió la propiedad del lote")

        files = list(db.scalars(
            select(IngestionFile)
            .where(
                IngestionFile.company_id == company_id,
                IngestionFile.batch_id == batch_id,
            )
            .order_by(IngestionFile.id)
        ).all())

        manifest_files = batch.request_manifest.get("files", [])

        if not files or len(files) != len(manifest_files):
            raise ProcessingError("El manifiesto no coincide con los archivos")

        # Asociamos por el nombre físico generado durante la recepción.
        # No dependemos del nombre original, que puede repetirse.
        formats = {
            item["position"]: item["format"]
            for item in manifest_files
        }

        source = db.scalar(select(Source).where(
            Source.id == batch.source_id, Source.company_id == company_id
        ))
        technology = db.get(Technology, source.technology_id) if source is not None else None
        if technology is None or not supports_technology(technology.code):
            raise ProcessingError("La tecnología de la fuente no está habilitada")

        root = get_settings().data_dir
        read = accepted = rejected = duplicates = 0

        # Un lote puede contener métricas y logs.
        versions = {
            "obsinf_metrics_jsonl_v1": METRICS_PARSER_VERSION,
            "weblogic_log_v1": LOG_PARSER_VERSION,
        }

        if any(
            format_name not in versions or not supports_format(technology.code, format_name)
            for format_name in formats.values()
        ):
            raise ProcessingError("Formato no habilitado para la tecnología de la fuente")

        batch.parser_version = ";".join(
            sorted({versions[format_name] for format_name in formats.values()})
        )

        for file in files:
            position = int(Path(file.storage_key).stem)

            format_name = formats.get(position)

            if format_name not in versions:
                raise ProcessingError("Formato de archivo no soportado")

            path = resolve_original(root, file.storage_key)
            verify_original(path, file)

            # Validamos toda la codificación antes de insertar métricas.
            # Así un error UTF-8 tardío no deja una carga incompleta.
            with path.open("r", encoding="utf-8-sig") as original:
                while original.read(64 * 1024):
                    pass

            file.status = "processing"
            file_rejected = 0
            file_usable = 0

            with path.open("r", encoding="utf-8-sig") as original:
                for result in normalized_records(
                    original, file, format_name, technology_code=technology.code
                ):
                    is_error = isinstance(
                        result, (ParseError, LogParseError)
                    )

                    # Para logs contamos registros lógicos:
                    # un stack trace multilínea es un solo registro.
                    if not (is_error and result.code == "EMPTY_FILE"):
                        read += 1

                    if is_error:
                        if result.code != "EMPTY_FILE":
                            rejected += 1

                        file_rejected += 1

                        db.add(IngestionError(
                            company_id=company_id,
                            batch_id=batch_id,
                            file_id=file.id,
                            record_locator=result.record_locator,
                            error_code=result.code,
                            message=result.message,
                        ))
                        continue

                    model, values = result

                    statement = (
                        insert(model)
                        .values(
                            company_id=company_id,
                            source_id=batch.source_id,
                            batch_id=batch_id,
                            file_id=file.id,
                            **values,
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                "company_id",
                                "source_id",
                                "dedup_key",
                            ]
                        )
                        .returning(model.id)
                    )

                    inserted_id = db.execute(
                        statement
                    ).scalar_one_or_none()

                    if inserted_id is None:
                        duplicates += 1
                    else:
                        accepted += 1

                    file_usable += 1

            file.status = (
                "processed" if file_rejected == 0
                else "partial" if file_usable > 0
                else "rejected"
            )
            file.processed_at = database_now(db)
            file.error_summary = (
                f"{file_rejected} errores de archivo o registros"
                if file_rejected else None
            )

            batch.heartbeat_at = database_now(db)

        batch.records_read = read
        batch.records_accepted = accepted
        batch.records_rejected = rejected
        batch.records_duplicate = duplicates

        has_errors = any(
            file.status in ("partial", "rejected")
            for file in files
        )

        batch.status = (
            "completed" if not has_errors
            else "partial" if accepted + duplicates > 0
            else "failed"
        )
        batch.error_summary = (
            "Existen archivos o registros rechazados"
            if has_errors else None
        )
        batch.finished_at = database_now(db)
        batch.heartbeat_at = batch.finished_at
        batch.processing_token = None

        result = {
            "batch_id": batch.id,
            "status": batch.status,
            "records_read": read,
            "records_accepted": accepted,
            "records_rejected": rejected,
            "records_duplicate": duplicates,
        }

        db.commit()
        return result

    except Exception:
        # Un fallo técnico revierte todo el trabajo de esta ejecución.
        db.rollback()

        batch = db.scalar(
            select(IngestionBatch)
            .where(
                IngestionBatch.id == batch_id,
                IngestionBatch.company_id == company_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        if (
            batch is not None
            and batch.processing_token == token
            and batch.status == "processing"
        ):
            batch.status = "failed"
            batch.finished_at = database_now(db)
            batch.processing_token = None
            batch.error_summary = (
                "Fallo técnico durante el procesamiento; revisar la ejecución"
            )
            db.commit()
        else:
            db.rollback()

        raise
