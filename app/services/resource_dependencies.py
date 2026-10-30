"""Administración de dependencias explícitas entre recursos."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.resource_dependency import ResourceDependency
from app.models.source import Source
from app.schemas.resource_dependency import DependencyCreate


class DependencyError(Exception):
    """Error de negocio traducible posteriormente a una respuesta HTTP."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _company(
    db: Session,
    company_id: int,
    *,
    lock: bool = False,
    require_active: bool = False,
) -> Company:
    statement = select(Company).where(Company.id == company_id)

    if lock:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )

    company = db.scalar(statement)

    if company is None:
        raise DependencyError(
            404, "COMPANY_NOT_FOUND", "Empresa no encontrada"
        )

    if require_active and not company.is_active:
        raise DependencyError(
            409, "COMPANY_INACTIVE", "La empresa está inactiva"
        )

    return company


def _active_sources(
    db: Session,
    company_id: int,
    consumer_id: int,
    provider_id: int,
) -> None:
    """Bloquea las fuentes en orden estable y comprueba su pertenencia."""
    for source_id in sorted({consumer_id, provider_id}):
        source = db.scalar(
            select(Source)
            .where(
                Source.company_id == company_id,
                Source.id == source_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        # Una fuente ajena se trata igual que una inexistente.
        if source is None:
            raise DependencyError(
                404, "SOURCE_NOT_FOUND", "Fuente no encontrada"
            )

        if not source.is_active:
            raise DependencyError(
                409, "SOURCE_INACTIVE", "La fuente está inactiva"
            )


def get_dependency(
    db: Session,
    company_id: int,
    dependency_id: int,
) -> ResourceDependency:
    """Consulta una relación exclusivamente dentro de su empresa."""
    _company(db, company_id)

    dependency = db.scalar(
        select(ResourceDependency).where(
            ResourceDependency.company_id == company_id,
            ResourceDependency.id == dependency_id,
        )
    )

    if dependency is None:
        raise DependencyError(
            404, "DEPENDENCY_NOT_FOUND", "Dependencia no encontrada"
        )

    return dependency


def list_dependencies(
    db: Session,
    company_id: int,
    *,
    is_active: bool | None = None,
    after_id: int = 0,
    limit: int = 100,
) -> list[ResourceDependency]:
    """Consulta por ID ascendente, con paginación acotada."""
    if type(after_id) is not int or after_id < 0:
        raise DependencyError(
            422, "INVALID_PAGINATION", "after_id debe ser un entero no negativo"
        )

    if type(limit) is not int or not 1 <= limit <= 1000:
        raise DependencyError(
            422, "INVALID_PAGINATION", "limit debe estar entre 1 y 1000"
        )

    if is_active is not None and type(is_active) is not bool:
        raise DependencyError(
            422, "INVALID_FILTER", "is_active debe ser booleano"
        )

    _company(db, company_id)

    statement = select(ResourceDependency).where(
        ResourceDependency.company_id == company_id,
        ResourceDependency.id > after_id,
    )

    if is_active is not None:
        statement = statement.where(
            ResourceDependency.is_active == is_active
        )

    return list(
        db.scalars(
            statement.order_by(ResourceDependency.id).limit(limit)
        )
    )


def create_dependency(
    db: Session,
    company_id: int,
    payload: DependencyCreate,
    *,
    configured_by: str,
) -> ResourceDependency:
    """Crea y confirma una relación; revierte la sesión ante errores."""
    try:
        if (
            not isinstance(configured_by, str)
            or not configured_by.strip()
            or len(configured_by) > 500
        ):
            raise DependencyError(
                422, "INVALID_OPERATOR", "Identidad del operador inválida"
            )

        _company(
            db, company_id, lock=True, require_active=True
        )
        _active_sources(
            db,
            company_id,
            payload.consumer_source_id,
            payload.provider_source_id,
        )

        if (
            payload.consumer_source_id == payload.provider_source_id
            and payload.consumer_resource_key
            == payload.provider_resource_key
        ):
            raise DependencyError(
                422,
                "SELF_DEPENDENCY",
                "Un recurso no puede depender de sí mismo",
            )

        # Serializar por empresa permite comprobar duplicados antes de
        # insertar; la restricción UNIQUE sigue siendo la protección final.
        existing = db.scalar(
            select(ResourceDependency.id).where(
                ResourceDependency.company_id == company_id,
                ResourceDependency.consumer_source_id
                == payload.consumer_source_id,
                ResourceDependency.consumer_resource_key
                == payload.consumer_resource_key,
                ResourceDependency.provider_source_id
                == payload.provider_source_id,
                ResourceDependency.provider_resource_key
                == payload.provider_resource_key,
                ResourceDependency.dependency_type
                == payload.dependency_type,
            )
        )

        if existing is not None:
            raise DependencyError(
                409,
                "DEPENDENCY_EXISTS",
                "La relación ya existe; puede consultarse o reactivarse",
            )

        dependency = ResourceDependency(
            company_id=company_id,
            **payload.model_dump(),
            configured_by=configured_by.strip(),
        )
        db.add(dependency)
        db.flush()
        db.refresh(dependency)
        db.commit()
        return dependency

    except IntegrityError as exc:
        db.rollback()
        diagnostic = getattr(exc.orig, "diag", None)

        if (
            getattr(exc.orig, "sqlstate", None) == "23505"
            and getattr(diagnostic, "constraint_name", None)
            == "uq_resource_dependencies_relationship"
        ):
            raise DependencyError(
                409, "DEPENDENCY_EXISTS", "La relación ya existe"
            ) from None

        raise

    except Exception:
        db.rollback()
        raise


def set_dependency_active(
    db: Session,
    company_id: int,
    dependency_id: int,
    *,
    is_active: bool,
) -> ResourceDependency:
    """Cambia el estado conservando la identidad de la relación.

    Desactivar se permite aunque la empresa o sus fuentes estén
    inactivas. Reactivar exige comprobar que siguen habilitadas.
    """
    try:
        if type(is_active) is not bool:
            raise DependencyError(
                422, "INVALID_STATUS", "is_active debe ser booleano"
            )

        _company(
            db,
            company_id,
            lock=True,
            require_active=is_active,
        )

        dependency = db.scalar(
            select(ResourceDependency)
            .where(
                ResourceDependency.company_id == company_id,
                ResourceDependency.id == dependency_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        if dependency is None:
            raise DependencyError(
                404, "DEPENDENCY_NOT_FOUND", "Dependencia no encontrada"
            )

        if is_active:
            _active_sources(
                db,
                company_id,
                dependency.consumer_source_id,
                dependency.provider_source_id,
            )

        # Evita modificar updated_at si el estado ya es el solicitado.
        dependency.is_active = is_active
        db.flush()
        db.refresh(dependency)
        db.commit()
        return dependency

    except Exception:
        db.rollback()
        raise