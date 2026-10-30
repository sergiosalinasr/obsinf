"""Respuestas públicas de las consultas de reportes."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReportRead(BaseModel):
    """Metadatos del reporte conservado."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    period_start: datetime
    period_end: datetime
    timezone: str
    generator_version: str
    request_sha256: str
    created_at: datetime


class ReportDetail(ReportRead):
    """Agrega el contenido exacto, sin regenerarlo."""

    content_markdown: str