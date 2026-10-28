from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.technology import Technology


def list_technologies(
    db: Session,
    active_only: bool = True,
) -> list[Technology]:
    """Consulta el catálogo global, ordenado por código.

    Por defecto devuelve únicamente tecnologías activas.
    """
    statement = select(Technology).order_by(Technology.code)

    if active_only:
        statement = statement.where(Technology.is_active.is_(True))

    return list(db.scalars(statement).all())