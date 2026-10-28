from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.source import Source
from app.models.technology import Technology
from app.schemas.source import SourceCreate


class SourceRegistrationError(Exception):
    """Error de negocio que el endpoint traducirá a una respuesta HTTP."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def create_source(
    db: Session,
    company_id: int,
    payload: SourceCreate,
) -> Source:
    """Registra una fuente dentro de una empresa activa."""
    try:
        # Bloqueamos las filas mientras comprobamos su estado y guardamos.
        # Así evitamos una desactivación concurrente durante el registro.
        company = db.scalar(
            select(Company)
            .where(Company.id == company_id)
            .with_for_update()
        )

        if company is None:
            raise SourceRegistrationError(
                404, "COMPANY_NOT_FOUND", "Empresa no encontrada"
            )

        if not company.is_active:
            raise SourceRegistrationError(
                409, "COMPANY_INACTIVE", "La empresa está inactiva"
            )

        technology = db.scalar(
            select(Technology)
            .where(Technology.id == payload.technology_id)
            .with_for_update()
        )

        if technology is None:
            raise SourceRegistrationError(
                404, "TECHNOLOGY_NOT_FOUND", "Tecnología no encontrada"
            )

        if not technology.is_active:
            raise SourceRegistrationError(
                409, "TECHNOLOGY_INACTIVE", "La tecnología está inactiva"
            )

        # Solo habilitamos el registro de fuentes WebLogic en esta etapa.
        # Esto no habilita todavía la carga ni el procesamiento de archivos.
        if technology.code != "weblogic":
            raise SourceRegistrationError(
                409,
                "TECHNOLOGY_NOT_SUPPORTED",
                "El registro de fuentes solo está habilitado para WebLogic",
            )

        source = Source(
            company_id=company_id,
            **payload.model_dump(),
        )
        db.add(source)
        db.commit()

    except IntegrityError as exc:
        db.rollback()

        sqlstate = getattr(exc.orig, "sqlstate", None)
        diagnostic = getattr(exc.orig, "diag", None)
        constraint = getattr(diagnostic, "constraint_name", None)

        if (
            sqlstate == "23505"
            and constraint == "uq_sources_company_id_code"
        ):
            raise SourceRegistrationError(
                409,
                "SOURCE_CODE_EXISTS",
                "Ya existe una fuente con ese código en la empresa",
            ) from None

        raise

    except Exception:
        db.rollback()
        raise

    db.refresh(source)
    return source

def list_sources(
    db: Session,
    company_id: int,
    after_id: int = 0,
    limit: int = 100,
) -> list[Source]:
    """Lista las fuentes de una empresa, incluidas las inactivas.

    Una empresa inactiva conserva acceso de consulta a su historial.
    """
    if db.get(Company, company_id) is None:
        raise SourceRegistrationError(
            404, "COMPANY_NOT_FOUND", "Empresa no encontrada"
        )

    statement = (
        select(Source)
        .where(
            Source.company_id == company_id,
            Source.id > after_id,
        )
        .order_by(Source.id)
        .limit(limit)
    )

    return list(db.scalars(statement).all())


def get_source(
    db: Session,
    company_id: int,
    source_id: int,
) -> Source:
    """Busca una fuente exclusivamente dentro de la empresa indicada."""
    if db.get(Company, company_id) is None:
        raise SourceRegistrationError(
            404, "COMPANY_NOT_FOUND", "Empresa no encontrada"
        )

    # No basta con buscar por source_id: comprobamos también company_id.
    source = db.scalar(
        select(Source).where(
            Source.id == source_id,
            Source.company_id == company_id,
        )
    )

    if source is None:
        # La misma respuesta evita revelar fuentes de otras empresas.
        raise SourceRegistrationError(
            404, "SOURCE_NOT_FOUND", "Fuente no encontrada"
        )

    return source