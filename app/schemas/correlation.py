"""Respuestas públicas de las consultas de correlaciones."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.analysis.coordinator_contract import CorrelationProposal


class CorrelationRead(BaseModel):
    """Resultado y procedencia, sin la copia completa de entrada."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    dependency_id: int
    consumer_finding_id: int
    provider_finding_id: int

    proposal: CorrelationProposal

    agent_name: str
    model_name: str
    prompt_sha256: str
    context_sha256: str
    request_sha256: str
    created_at: datetime


class CorrelationDetail(CorrelationRead):
    """Incluye el contexto exacto conservado durante la interpretación."""

    context_snapshot: dict[str, Any]