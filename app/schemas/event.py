from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class EventRead(BaseModel):
    """Evento normalizado con referencias al registro original."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    source_id: int
    batch_id: int
    file_id: int | None
    record_locator: str | None
    resource_key: str
    record_type: str
    severity: str
    original_severity: str | None
    event_code: str | None
    message: str
    occurred_at: datetime
    received_at: datetime
    attributes: dict[str, Any]


class EventPage(BaseModel):
    """Página de eventos y cursor para continuar."""

    items: list[EventRead]
    next_cursor: str | None