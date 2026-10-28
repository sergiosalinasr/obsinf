from pydantic import BaseModel, ConfigDict


class TechnologyRead(BaseModel):
    """Información pública de una tecnología del catálogo."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None
    is_active: bool