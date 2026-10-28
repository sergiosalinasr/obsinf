from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AnalysisExecutionRead(BaseModel):
    """Información pública de una ejecución de análisis."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    profile_id: int
    profile_code: str
    profile_version: str
    detector_version: str
    period_start: datetime
    period_end: datetime
    data_cutoff_at: datetime
    status: str
    coverage: list[dict[str, Any]]
    started_at: datetime
    finished_at: datetime | None
    error_summary: str | None


class EvidenceRead(BaseModel):
    """Evidencia técnica y referencias a sus mediciones."""

    id: int
    company_id: int
    execution_id: int
    rule_id: int
    source_id: int
    evidence_type: str
    resource_key: str
    metric_name: str
    unit: str
    series_key: str
    comparison: str
    threshold_value: float
    min_observed: float
    max_observed: float
    start_at: datetime
    end_at: datetime
    duration_seconds: float
    sample_count: int
    created_at: datetime
    metric_ids: list[int]


class EvidencePage(BaseModel):
    """Página de evidencias ordenadas por identificador."""

    items: list[EvidenceRead]
    next_after_id: int | None