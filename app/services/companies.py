from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.company import Company
from app.schemas.company import CompanyCreate, CompanyUpdate
from sqlalchemy import select

class CompanyCodeAlreadyExists(Exception):
    pass


def create_company(db: Session, payload: CompanyCreate) -> Company:
    company = Company(**payload.model_dump())
    db.add(company)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()

        sqlstate = getattr(exc.orig, "sqlstate", None)
        diagnostic = getattr(exc.orig, "diag", None)
        constraint = getattr(diagnostic, "constraint_name", None)

        if sqlstate == "23505" and constraint == "uq_companies_code":
            raise CompanyCodeAlreadyExists from None

        raise

    db.refresh(company)
    return company

def list_companies(
    db: Session,
    after_id: int = 0,
    limit: int = 100,
) -> list[Company]:
    """Consulta empresas por páginas, ordenadas por su ID.

    after_id permite continuar después de la última empresa recibida.
    Incluye empresas activas e inactivas para administración local.
    """
    statement = (
        select(Company)
        .where(Company.id > after_id)
        .order_by(Company.id)
        .limit(limit)
    )

    return list(db.scalars(statement).all())


def get_company(db: Session, company_id: int) -> Company | None:
    """Busca una empresa por su clave primaria.

    Devuelve None cuando el identificador no existe.
    """
    return db.get(Company, company_id)

def update_company(
    db: Session,
    company_id: int,
    payload: CompanyUpdate,
) -> Company | None:
    """Actualiza únicamente los campos enviados.

    Una empresa inactiva puede reactivarse.
    Desactivarla conserva sus fuentes y datos históricos.
    """
    company = db.get(Company, company_id)

    if company is None:
        return None

    # exclude_unset evita reemplazar campos que no fueron enviados.
    changes = payload.model_dump(exclude_unset=True)

    for field, value in changes.items():
        setattr(company, field, value)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(company)
    return company