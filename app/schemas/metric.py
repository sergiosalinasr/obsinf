from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class MetricRead(BaseModel):
    """Medición normalizada con referencias a su origen."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    source_id: int
    batch_id: int
    file_id: int | None
    record_locator: str | None
    resource_key: str
    metric_name: str
    value: float
    unit: str
    observed_at: datetime
    received_at: datetime
    attributes: dict[str, Any]


class MetricPage(BaseModel):
    """Página de resultados y cursor para continuar la consulta."""

    items: list[MetricRead]
    next_cursor: str | None