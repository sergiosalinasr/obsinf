import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.company import Company
from app.models.ingestion import (
    IngestionBatch,
    IngestionError,
    IngestionFile,
)
from app.models.source import Source
from app.models.technology import Technology
from app.schemas.ingestion import IngestionManifest


class IngestionServiceError(Exception):
    """Error esperado que el endpoint convertirá a una respuesta HTTP."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def canonical_json(value) -> str:
    """Produce una representación estable para calcular la huella."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def receive_ingestion(
    db: Session,
    company_id: int,
    source_id: int,
    idempotency_key: str,
    manifest: IngestionManifest,
    uploads: list[UploadFile],
) -> IngestionBatch:
    """Conserva originales y registra un lote pendiente.

    Los archivos se leen por bloques. No se ejecuta aquí el parser.
    La carpeta física usa nombres generados, nunca rutas del usuario.
    """
    settings = get_settings()
    root = settings.data_dir

    if len(uploads) != len(manifest.files):
        raise IngestionServiceError(
            422, "MANIFEST_MISMATCH",
            "El manifiesto debe describir todos los archivos",
        )

    if len(uploads) > settings.max_files_per_batch:
        raise IngestionServiceError(
            413, "TOO_MANY_FILES", "Se excedió la cantidad de archivos"
        )

    # Comprobación inicial antes de recibir contenido en almacenamiento.
    source = db.scalar(
        select(Source).where(
            Source.id == source_id,
            Source.company_id == company_id,
        )
    )

    if source is None:
        raise IngestionServiceError(
            404, "SOURCE_NOT_FOUND", "Fuente no encontrada"
        )

    staging_root = root / "incoming"
    final_directory: Path | None = None
    committed = False

    try:
        staging_root.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory(dir=staging_root) as temporary:
            temporary_path = Path(temporary)
            staged = []
            total_size = 0
            formats = {
                item.position: item.format
                for item in manifest.files
            }

            for position, upload in enumerate(uploads):
                # Se conserva como metadato; nunca se usa como ruta física.
                original_name = upload.filename or f"file_{position}"
                size = 0
                digest = hashlib.sha256()
                staged_path = temporary_path / str(position)

                with staged_path.open("wb") as destination:
                    while chunk := upload.file.read(1024 * 1024):
                        size += len(chunk)
                        total_size += len(chunk)

                        if size > settings.max_file_size_mb * 1024 * 1024:
                            raise IngestionServiceError(
                                413, "FILE_TOO_LARGE",
                                "Un archivo excede el tamaño permitido",
                            )

                        if total_size > settings.max_batch_size_mb * 1024 * 1024:
                            raise IngestionServiceError(
                                413, "BATCH_TOO_LARGE",
                                "La carga excede el tamaño total permitido",
                            )

                        digest.update(chunk)
                        destination.write(chunk)

                staged.append({
                    "position": position,
                    "original_filename": original_name,
                    "format": formats[position],
                    "sha256": digest.hexdigest(),
                    "size_bytes": size,
                    "content_type": upload.content_type,
                })

            # Conservamos el manifiesto efectivo junto con los hashes.
            request_manifest = {"files": staged}
            fingerprint = hashlib.sha256(
                canonical_json(request_manifest).encode("utf-8")
            ).hexdigest()

            # Serializamos las recepciones de una empresa durante el registro.
            # El mismo orden de bloqueo se utiliza al registrar fuentes.
            company = db.scalar(
                select(Company)
                .where(Company.id == company_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )

            source = db.scalar(
                select(Source)
                .where(
                    Source.id == source_id,
                    Source.company_id == company_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )

            if company is None or source is None:
                raise IngestionServiceError(
                    404, "SOURCE_NOT_FOUND", "Fuente no encontrada"
                )

            existing = db.scalar(
                select(IngestionBatch).where(
                    IngestionBatch.company_id == company_id,
                    IngestionBatch.source_id == source_id,
                    IngestionBatch.idempotency_key == idempotency_key,
                )
            )

            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise IngestionServiceError(
                        409, "IDEMPOTENCY_CONFLICT",
                        "La clave ya fue utilizada con otro contenido",
                    )

                # Una repetición devuelve el resultado existente.
                # El commit libera los bloqueos; no crea otro lote.
                db.commit()
                committed = True
                return existing

            if not company.is_active or not source.is_active:
                raise IngestionServiceError(
                    409, "INACTIVE_ORIGIN",
                    "La empresa o la fuente está inactiva",
                )

            technology = db.get(Technology, source.technology_id)

            if (
                source.ingestion_method != "file"
                or technology is None
                or not technology.is_active
                or technology.code != "weblogic"
            ):
                raise IngestionServiceError(
                    409, "INGESTION_NOT_SUPPORTED",
                    "La fuente no admite esta carga",
                )

            batch = IngestionBatch(
                company_id=company_id,
                source_id=source_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                request_manifest=request_manifest,
                requested_by="local-dev",
            )
            db.add(batch)
            db.flush()

            date_path = datetime.now(timezone.utc).strftime("%Y/%m/%d")
            relative_directory = (
                Path("companies") / str(company_id) / "raw"
                / str(source_id) / date_path
                / f"{batch.id}_{uuid4().hex}"
            )
            final_directory = root / relative_directory
            final_directory.mkdir(parents=True, exist_ok=False)

            for item in staged:
                position = item["position"]
                # La extensión refleja el formato declarado.
                extension = (
                    "log" if item["format"] == "weblogic_log_v1"
                    else "jsonl"
                )
                physical_name = f"{position}.{extension}"
                destination = final_directory / physical_name

                shutil.move(
                    str(temporary_path / str(position)),
                    str(destination),
                )

                db.add(IngestionFile(
                    company_id=company_id,
                    batch_id=batch.id,
                    original_filename=item["original_filename"],
                    storage_key=(
                        relative_directory / physical_name
                    ).as_posix(),
                    sha256=item["sha256"],
                    size_bytes=item["size_bytes"],
                    content_type=item["content_type"],
                ))

            db.commit()
            committed = True
            return batch

    except Exception:
        if not committed:
            db.rollback()

            # Eliminamos únicamente la carpeta creada por esta solicitud.
            if final_directory is not None and final_directory.exists():
                shutil.rmtree(final_directory)

        raise

def get_ingestion(
    db: Session,
    company_id: int,
    batch_id: int,
) -> tuple[IngestionBatch, list[IngestionFile]]:
    """Consulta un lote y sus archivos dentro de la empresa indicada.

    Una empresa inactiva puede consultar sus cargas históricas.
    Un lote ajeno se trata igual que un lote inexistente.
    """
    batch = db.scalar(
        select(IngestionBatch).where(
            IngestionBatch.id == batch_id,
            IngestionBatch.company_id == company_id,
        )
    )

    if batch is None:
        raise IngestionServiceError(
            404,
            "INGESTION_NOT_FOUND",
            "Lote de ingesta no encontrado",
        )

    files = list(
        db.scalars(
            select(IngestionFile)
            .where(
                IngestionFile.company_id == company_id,
                IngestionFile.batch_id == batch_id,
            )
            .order_by(IngestionFile.id)
        ).all()
    )

    return batch, files

def list_ingestion_errors(
    db: Session,
    company_id: int,
    batch_id: int,
    after_id: int = 0,
    limit: int = 100,
) -> tuple[list[IngestionError], int | None]:
    """Consulta errores únicamente dentro del lote y empresa indicados."""
    batch_exists = db.scalar(
        select(IngestionBatch.id).where(
            IngestionBatch.id == batch_id,
            IngestionBatch.company_id == company_id,
        )
    )

    if batch_exists is None:
        raise IngestionServiceError(
            404,
            "INGESTION_NOT_FOUND",
            "Lote de ingesta no encontrado",
        )

    # Una fila adicional indica si existe una página siguiente.
    rows = list(db.scalars(
        select(IngestionError)
        .where(
            IngestionError.company_id == company_id,
            IngestionError.batch_id == batch_id,
            IngestionError.id > after_id,
        )
        .order_by(IngestionError.id)
        .limit(limit + 1)
    ).all())

    items = rows[:limit]
    next_after_id = items[-1].id if len(rows) > limit else None

    return items, next_after_id