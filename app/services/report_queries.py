"""Consultas de reportes con aislamiento por empresa."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.report import Report


class ReportQueryError(Exception):
    """Error de consulta traducible a una respuesta HTTP."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _require_company(db: Session, company_id: int) -> None:
    """Permite consultar históricos de empresas desactivadas."""
    if db.get(Company, company_id) is None:
        raise ReportQueryError(
            404, "COMPANY_NOT_FOUND", "Empresa no encontrada"
        )


def list_reports(
    db: Session,
    company_id: int,
    *,
    after_id: int = 0,
    limit: int = 100,
) -> list[Report]:
    """Lista reportes por ID ascendente, sin confirmar transacciones."""
    if type(after_id) is not int or after_id < 0:
        raise ReportQueryError(
            422,
            "INVALID_PAGINATION",
            "after_id debe ser un entero no negativo",
        )

    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ReportQueryError(
            422,
            "INVALID_PAGINATION",
            "limit debe estar entre 1 y 1000",
        )

    _require_company(db, company_id)

    return list(db.scalars(
        select(Report)
        .where(
            Report.company_id == company_id,
            Report.id > after_id,
        )
        .order_by(Report.id)
        .limit(limit)
    ))


def get_report(
    db: Session,
    company_id: int,
    report_id: int,
) -> Report:
    """Un reporte de otra empresa se trata como inexistente."""
    _require_company(db, company_id)

    report = db.scalar(
        select(Report).where(
            Report.company_id == company_id,
            Report.id == report_id,
        )
    )

    if report is None:
        raise ReportQueryError(
            404, "REPORT_NOT_FOUND", "Reporte no encontrado"
        )

    return report