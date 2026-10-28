from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_local_dev
from app.db.session import get_db
from app.schemas.technology import TechnologyRead
from app.services.technologies import list_technologies


router = APIRouter(
    prefix="/technologies",
    tags=["technologies"],
    dependencies=[Depends(require_local_dev)],
)


@router.get(
    "",
    response_model=list[TechnologyRead],
    responses={
        403: {"description": "Acceso no habilitado"},
    },
)
def get_technologies(
    db: Annotated[Session, Depends(get_db)],
    active_only: Annotated[
        bool,
        Query(description="Devuelve solo tecnologías activas"),
    ] = True,
) -> list[TechnologyRead]:
    """Consulta las tecnologías registradas en OBSINF."""
    technologies = list_technologies(db, active_only=active_only)

    return [
        TechnologyRead.model_validate(technology)
        for technology in technologies
    ]