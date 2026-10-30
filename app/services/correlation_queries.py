"""Consultas de correlaciones con aislamiento por empresa."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.correlation import Correlation


class CorrelationQueryError(Exception):
    """Error de consulta traducible a una respuesta HTTP."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _require_company(db: Session, company_id: int) -> None:
    """Permite consultar históricos de empresas desactivadas."""
    if db.get(Company, company_id) is None:
        raise CorrelationQueryError(
            404, "COMPANY_NOT_FOUND", "Empresa no encontrada"
        )


def list_correlations(
    db: Session,
    company_id: int,
    *,
    dependency_id: int | None = None,
    after_id: int = 0,
    limit: int = 100,
) -> list[Correlation]:
    """Lista resultados por ID ascendente sin confirmar transacciones."""
    if type(after_id) is not int or after_id < 0:
        raise CorrelationQueryError(
            422, "INVALID_PAGINATION", "after_id debe ser no negativo"
        )

    if type(limit) is not int or not 1 <= limit <= 1000:
        raise CorrelationQueryError(
            422, "INVALID_PAGINATION", "limit debe estar entre 1 y 1000"
        )

    if dependency_id is not None and (
        type(dependency_id) is not int or dependency_id <= 0
    ):
        raise CorrelationQueryError(
            422, "INVALID_FILTER", "dependency_id debe ser positivo"
        )

    _require_company(db, company_id)

    statement = select(Correlation).where(
        Correlation.company_id == company_id,
        Correlation.id > after_id,
    )
    if dependency_id is not None:
        statement = statement.where(
            Correlation.dependency_id == dependency_id
        )

    return list(
        db.scalars(
            statement.order_by(Correlation.id).limit(limit)
        )
    )


def get_correlation(
    db: Session,
    company_id: int,
    correlation_id: int,
) -> Correlation:
    """Un registro de otra empresa se trata como inexistente."""
    _require_company(db, company_id)

    correlation = db.scalar(
        select(Correlation).where(
            Correlation.company_id == company_id,
            Correlation.id == correlation_id,
        )
    )

    if correlation is None:
        raise CorrelationQueryError(
            404, "CORRELATION_NOT_FOUND", "Correlación no encontrada"
        )

    return correlation