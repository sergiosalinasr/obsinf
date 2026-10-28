"""Consultas de hallazgos; no ejecutan agentes ni modifican datos."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.finding import Finding, FindingEvidence
from app.schemas.finding import (
    FindingClassification,
    FindingRead,
    FindingSeverity,
)


class FindingQueryError(Exception):
    """Error esperado que el endpoint transforma en una respuesta pública."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _require_company(db: Session, company_id: int) -> None:
    """Permite consultar el historial de empresas incluso desactivadas."""
    exists = db.scalar(select(Company.id).where(Company.id == company_id))
    if exists is None:
        raise FindingQueryError("COMPANY_NOT_FOUND", "Empresa no encontrada")


def _serialize_findings(
    db: Session, company_id: int, rows: list[Finding]
) -> list[FindingRead]:
    """Carga las asociaciones en una consulta para evitar N+1 consultas."""
    if not rows:
        return []

    evidence_by_finding: dict[int, list[int]] = {row.id: [] for row in rows}
    links = db.execute(
        select(FindingEvidence.finding_id, FindingEvidence.evidence_id)
        .where(
            FindingEvidence.company_id == company_id,
            FindingEvidence.finding_id.in_(evidence_by_finding),
        )
        .order_by(FindingEvidence.finding_id, FindingEvidence.evidence_id)
    ).all()
    for finding_id, evidence_id in links:
        evidence_by_finding[finding_id].append(evidence_id)

    return [
        FindingRead.model_validate({
            # Se exponen solamente los campos definidos en el contrato público.
            **{
                name: getattr(row, name)
                for name in FindingRead.model_fields
                if name != "evidence_ids"
            },
            "evidence_ids": evidence_by_finding[row.id],
        })
        for row in rows
    ]


def get_finding(db: Session, company_id: int, finding_id: int) -> FindingRead:
    """Un ID inexistente o de otra empresa produce la misma respuesta."""
    row = db.scalar(
        select(Finding).where(
            Finding.company_id == company_id,
            Finding.id == finding_id,
        )
    )
    if row is None:
        raise FindingQueryError("FINDING_NOT_FOUND", "Hallazgo no encontrado")
    return _serialize_findings(db, company_id, [row])[0]


def list_findings(
    db: Session,
    *,
    company_id: int,
    execution_id: int | None = None,
    source_id: int | None = None,
    resource_key: str | None = None,
    classification: FindingClassification | None = None,
    severity: FindingSeverity | None = None,
    after_id: int = 0,
    limit: int = 100,
) -> tuple[list[FindingRead], int | None]:
    """Filtra por igualdad y pagina sin OFFSET, siempre dentro de la empresa.

    Un filtro sin coincidencias devuelve una página vacía, incluso si
    execution_id o source_id corresponden a otra empresa. No se revela
    la existencia de esos objetos. El cursor es un ID, no una autorización.
    """
    if company_id <= 0 or after_id < 0 or not 1 <= limit <= 1000:
        raise ValueError("Identificador, cursor o límite inválidos")
    if any(value is not None and value <= 0 for value in (execution_id, source_id)):
        raise ValueError("Los identificadores de filtros deben ser positivos")

    _require_company(db, company_id)
    statement = select(Finding).where(
        Finding.company_id == company_id,
        Finding.id > after_id,
    )
    for column, value in (
        (Finding.execution_id, execution_id),
        (Finding.source_id, source_id),
        (Finding.resource_key, resource_key),
        (Finding.classification, classification),
        (Finding.severity, severity),
    ):
        if value is not None:
            statement = statement.where(column == value)

    # La fila adicional permite saber si hay otra página sin un COUNT global.
    rows = list(db.scalars(statement.order_by(Finding.id).limit(limit + 1)).all())
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_after_id = page_rows[-1].id if has_more else None
    return _serialize_findings(db, company_id, page_rows), next_after_id
