from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from datetime import datetime


class ManifestFile(BaseModel):
    """Identifica un archivo por su posición en la solicitud."""

    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=0)

    # Por ahora solo recibimos el formato cuyo parser está implementado.
    format: Literal[
        "obsinf_metrics_jsonl_v1",
        "weblogic_log_v1",
    ]


class IngestionManifest(BaseModel):
    """Declara el formato de cada archivo recibido."""

    model_config = ConfigDict(extra="forbid")

    files: list[ManifestFile] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_positions(self):
        """Exige posiciones consecutivas, sin duplicados, desde cero."""
        positions = sorted(item.position for item in self.files)

        if positions != list(range(len(self.files))):
            raise ValueError(
                "Las posiciones deben ser únicas y consecutivas desde 0"
            )

        return self


class IngestionAccepted(BaseModel):
    """Resultado de recepción; no significa que el archivo fue procesado."""

    batch_id: int
    status: str
    status_url: str

class IngestionFileRead(BaseModel):
    """Metadatos públicos de un archivo recibido."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    size_bytes: int
    sha256: str
    content_type: str | None
    status: str
    received_at: datetime
    processed_at: datetime | None
    error_summary: str | None


class IngestionBatchRead(BaseModel):
    """Estado y resultado de un lote, sin información interna sensible."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    source_id: int
    status: str
    parser_version: str | None
    attempt_count: int

    received_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    records_read: int
    records_accepted: int
    records_rejected: int
    records_duplicate: int
    error_summary: str | None

    files: list[IngestionFileRead]

class IngestionErrorRead(BaseModel):
    """Error de carga con referencia al archivo y registro afectado."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    file_id: int | None
    record_locator: str | None
    error_code: str
    message: str
    created_at: datetime


class IngestionErrorPage(BaseModel):
    """Página de errores y posición para continuar consultando."""

    items: list[IngestionErrorRead]
    next_after_id: int | None