"""Persistencia validada de correlaciones."""

import hashlib
import json
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.specialist_runtime import AgentConfiguration
from app.analysis.coordinator_contract import (
    CorrelationProposal,
    validate_correlation_context,
)
from app.models.correlation import Correlation
from app.models.resource_dependency import ResourceDependency
from app.services.dependency_context import build_dependency_context


class CorrelationError(Exception):
    """Error esperado al comprobar o guardar una correlación."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: dict) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _identity(
    context: dict,
    configuration: AgentConfiguration,
) -> tuple[str, str, str]:
    """Identifica entrada, prompt y solicitud de interpretación."""
    if configuration.agent_name != "dependency_coordinator":
        raise CorrelationError(
            "INVALID_AGENT", "Se requiere el agente coordinador"
        )

    if (
        not configuration.model_name.strip()
        or not configuration.instruction.strip()
    ):
        raise CorrelationError(
            "INVALID_PROVENANCE", "Se requieren modelo e instrucción"
        )

    context_hash = _digest(_canonical(context))
    prompt_hash = _digest(configuration.instruction)

    request_hash = _digest(_canonical({
        "context_sha256": context_hash,
        "prompt_sha256": prompt_hash,
        "agent_name": configuration.agent_name,
        "model_name": configuration.model_name,
    }))
    return context_hash, prompt_hash, request_hash


def ensure_correlation_not_saved(
    db: Session,
    *,
    company_id: int,
    context: dict,
    configuration: AgentConfiguration,
) -> None:
    """Evita invocar al modelo para una solicitud ya guardada.

    La comprobación definitiva permanece en save_correlation.
    """
    _, _, request_hash = _identity(context, configuration)

    existing = db.scalar(
        select(Correlation.id).where(
            Correlation.company_id == company_id,
            Correlation.request_sha256 == request_hash,
        )
    )
    if existing is not None:
        raise CorrelationError(
            "CORRELATION_EXISTS",
            f"La solicitud ya tiene la correlación {existing}",
        )


def save_correlation(
    db: Session,
    *,
    company_id: int,
    context: dict,
    proposal: CorrelationProposal,
    configuration: AgentConfiguration,
) -> Correlation:
    """Valida y guarda atómicamente; administra commit y rollback.

    Debe recibir una sesión dedicada a esta operación.
    """
    try:
        snapshot = deepcopy(context)

        if (
            type(company_id) is not int
            or company_id <= 0
            or snapshot.get("company_id") != company_id
        ):
            raise CorrelationError(
                "INVALID_COMPANY", "El contexto pertenece a otra empresa"
            )

        # Serializa las escrituras y los cambios de la dependencia.
        dependency = db.scalar(
            select(ResourceDependency)
            .where(
                ResourceDependency.company_id == company_id,
                ResourceDependency.id == snapshot["dependency"]["id"],
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if dependency is None:
            raise CorrelationError(
                "DEPENDENCY_NOT_FOUND", "Dependencia no encontrada"
            )

        current = build_dependency_context(
            db,
            company_id=company_id,
            dependency_id=dependency.id,
            consumer_finding_id=snapshot["consumer"]["finding"]["id"],
            provider_finding_id=snapshot["provider"]["finding"]["id"],
        )

        if _canonical(current) != _canonical(snapshot):
            raise CorrelationError(
                "CONTEXT_CHANGED",
                "El contexto cambió desde la interpretación; vuelve a ejecutarla",
            )

        # Revalida incluso si el llamador ya comprobó la respuesta del LLM.
        validated = CorrelationProposal.model_validate(
            proposal.model_dump(mode="json")
        )
        validate_correlation_context(validated, snapshot)

        context_hash, prompt_hash, request_hash = _identity(
            snapshot, configuration
        )
        ensure_correlation_not_saved(
            db,
            company_id=company_id,
            context=snapshot,
            configuration=configuration,
        )

        correlation = Correlation(
            company_id=company_id,
            dependency_id=dependency.id,
            consumer_finding_id=snapshot["consumer"]["finding"]["id"],
            provider_finding_id=snapshot["provider"]["finding"]["id"],
            proposal=validated.model_dump(mode="json"),
            context_snapshot=snapshot,
            agent_name=configuration.agent_name,
            model_name=configuration.model_name,
            prompt_sha256=prompt_hash,
            context_sha256=context_hash,
            request_sha256=request_hash,
        )
        db.add(correlation)
        db.flush()
        db.refresh(correlation)
        db.commit()
        return correlation

    except IntegrityError as exc:
        db.rollback()
        diagnostic = getattr(exc.orig, "diag", None)

        if (
            getattr(exc.orig, "sqlstate", None) == "23505"
            and getattr(diagnostic, "constraint_name", None)
            == "uq_correlations_company_request"
        ):
            raise CorrelationError(
                "CORRELATION_EXISTS", "La solicitud ya fue guardada"
            ) from None
        raise

    except Exception:
        db.rollback()
        raise