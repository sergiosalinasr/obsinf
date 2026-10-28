"""Respuestas públicas para la consulta de hallazgos persistidos."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


FindingClassification = Literal[
    "NORMAL", "EVENT", "ANOMALY", "RISK", "DEGRADATION", "INCIDENT"
]
FindingSeverity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]


class FindingRead(BaseModel):
    """Hallazgo, procedencia del agente y evidencias que lo sustentan.

    La confianza es la estimación declarada por el agente;
    no representa una probabilidad calibrada.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    execution_id: int
    source_id: int
    resource_key: str
    start_at: datetime
    end_at: datetime
    classification: FindingClassification
    severity: FindingSeverity
    confidence: float = Field(ge=0, le=1)
    finding: str
    possible_implications: list[str]
    agent_name: str
    model_name: str
    prompt_sha256: str
    created_at: datetime
    evidence_ids: list[int]


class FindingPage(BaseModel):
    """Página ordenada por ID ascendente.

    Para continuar, conservar los filtros y enviar next_after_id
    como after_id. Un valor nulo indica que no hay otra página.
    """

    items: list[FindingRead]
    next_after_id: int | None
