import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.event_context import EventContext, validate_event_citations
from app.services.event_context import load_event_context
from app.analysis.finding_contract import (
    FindingProposal,
    validate_finding_context,
)
from app.models.analysis import AnalysisExecution, Evidence
from app.models.finding import Finding, FindingEvidence, FindingEvent
from app.models.source import Source
from app.models.technology import Technology


class FindingPersistenceError(Exception):
    """Error esperado al validar o guardar un hallazgo."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def save_finding(
    db: Session,
    *,
    company_id: int,
    execution_id: int,
    source_id: int,
    proposal: FindingProposal,
    agent_name: str,
    model_name: str,
    instruction: str,
    event_context: EventContext | None = None,
) -> Finding:
    """Valida y guarda un hallazgo con sus evidencias.

    La sesión debe estar dedicada a esta operación: la función ejecuta
    commit al terminar y rollback ante errores.

    Para evitar duplicados, se permite un hallazgo por combinación de
    ejecución, fuente, recurso y agente mediante este servicio.
    """
    try:
        if min(company_id, execution_id, source_id) <= 0:
            raise FindingPersistenceError(
                "INVALID_CONTEXT",
                "Los identificadores deben ser positivos",
            )

        if not agent_name.strip() or not model_name.strip():
            raise FindingPersistenceError(
                "INVALID_PROVENANCE",
                "Se requieren nombre de agente y modelo",
            )

        if not instruction.strip():
            raise FindingPersistenceError(
                "INVALID_PROVENANCE",
                "Se requiere la instrucción utilizada por el agente",
            )

        # Serializa las escrituras de hallazgos para la misma ejecución.
        execution = db.scalar(
            select(AnalysisExecution)
            .where(
                AnalysisExecution.company_id == company_id,
                AnalysisExecution.id == execution_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        if execution is None:
            raise FindingPersistenceError(
                "ANALYSIS_NOT_FOUND",
                "Ejecución no encontrada en la empresa",
            )

        if execution.status not in ("completed", "partial"):
            raise FindingPersistenceError(
                "ANALYSIS_NOT_READY",
                "La ejecución no está disponible para interpretación",
            )

        source = db.scalar(
            select(Source)
            .join(Technology, Source.technology_id == Technology.id)
            .where(
                Source.company_id == company_id,
                Source.id == source_id,
                Technology.code == "weblogic",
            )
        )

        if source is None:
            raise FindingPersistenceError(
                "SOURCE_NOT_FOUND",
                "Fuente WebLogic no encontrada en la empresa",
            )

        # La validación estructural se hizo al construir FindingProposal.
        # Ahora verificamos los IDs contra el contexto autorizado en BD.
        evidence_rows = list(
            db.scalars(
                select(Evidence).where(
                    Evidence.company_id == company_id,
                    Evidence.execution_id == execution_id,
                    Evidence.source_id == source_id,
                    Evidence.resource_key == proposal.resource_key,
                    Evidence.id.in_(proposal.evidence_ids),
                )
            ).all()
        )

        evidence_by_id = {
            item.id: item for item in evidence_rows
        }

        if set(evidence_by_id) != set(proposal.evidence_ids):
            raise FindingPersistenceError(
                "INVALID_EVIDENCE",
                "Una o más evidencias no pertenecen al contexto",
            )

        evidence_periods = {
            item.id: (item.start_at, item.end_at)
            for item in evidence_rows
        }

        try:
            validate_finding_context(
                proposal,
                expected_resource=proposal.resource_key,
                allowed_evidence_ids=set(evidence_by_id),
                evidence_periods=evidence_periods,
            )
        except ValueError as exc:
            raise FindingPersistenceError(
                "INVALID_PROPOSAL",
                "El hallazgo no cubre el período de sus evidencias",
            ) from exc

        # El modelo nunca decide qué eventos están autorizados. Se comprueba
        # otra vez la selección completa contra BD antes de guardar referencias.
        try:
            validate_event_citations(proposal, event_context)
            if event_context is not None:
                if (
                    event_context.company_id != company_id
                    or event_context.execution_id != execution_id
                    or event_context.source_id != source_id
                    or event_context.resource_key != proposal.resource_key
                ):
                    raise ValueError("El contexto de eventos pertenece a otro análisis")
                if not set(proposal.evidence_ids).issubset(
                    {window.evidence_id for window in event_context.windows}
                ):
                    raise ValueError("Las evidencias no pertenecen al contexto de eventos")
                refreshed = load_event_context(
                    db,
                    company_id=company_id, execution_id=execution_id,
                    source_id=source_id, resource_key=proposal.resource_key,
                    evidence_ids=[window.evidence_id for window in event_context.windows],
                    margin_seconds=event_context.margin_seconds,
                    event_limit=event_context.event_limit,
                    max_message_chars=event_context.max_message_chars,
                )
                if refreshed.model_dump() != event_context.model_dump():
                    raise ValueError("El contexto de eventos cambió desde la interpretación")
        except ValueError as exc:
            raise FindingPersistenceError(
                "INVALID_EVENT_CONTEXT", str(exc)
            ) from exc

        existing = db.scalar(
            select(Finding.id)
            .where(
                Finding.company_id == company_id,
                Finding.execution_id == execution_id,
                Finding.source_id == source_id,
                Finding.resource_key == proposal.resource_key,
                Finding.agent_name == agent_name.strip(),
            )
            .limit(1)
        )

        if existing is not None:
            raise FindingPersistenceError(
                "FINDING_ALREADY_EXISTS",
                "Ya existe un hallazgo de este agente para el recurso",
            )

        # Se calcula sobre la instrucción exacta que recibió el agente.
        prompt_sha256 = hashlib.sha256(
            instruction.encode("utf-8")
        ).hexdigest()

        finding = Finding(
            company_id=company_id,
            execution_id=execution_id,
            source_id=source_id,
            resource_key=proposal.resource_key,
            start_at=proposal.start,
            end_at=proposal.end,
            classification=proposal.classification.value,
            severity=proposal.severity.value,
            confidence=proposal.confidence,
            finding=proposal.finding,
            possible_implications=proposal.possible_implications,
            agent_name=agent_name.strip(),
            model_name=model_name.strip(),
            prompt_sha256=prompt_sha256,
            event_context=(event_context.model_dump(mode="json") if event_context else {}),
        )
        db.add(finding)
        db.flush()

        for evidence_id in proposal.evidence_ids:
            db.add(FindingEvidence(
                company_id=company_id,
                finding_id=finding.id,
                evidence_id=evidence_id,
            ))

        for event_id in proposal.event_ids:
            db.add(FindingEvent(
                company_id=company_id, finding_id=finding.id, event_id=event_id
            ))

        db.commit()
        db.refresh(finding)
        return finding

    except Exception:
        db.rollback()
        raise
