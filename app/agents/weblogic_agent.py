import os
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

from app.agents.specialist_runtime import AgentConfiguration, run_specialist
from app.agents.weblogic_prompt import (
    PROJECT_ROOT,
    build_weblogic_message,
    load_weblogic_instruction,
)
from app.analysis.event_context import EventContext, validate_event_citations
from app.analysis.finding_contract import (
    FindingProposal,
    validate_finding_context,
)


def load_agent_configuration() -> AgentConfiguration:
    """Carga el modelo y el prompt usados por esta ejecución."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key or api_key == "your_openai_api_key_here":
        raise ValueError(
            "Configura OPENAI_API_KEY en el .env de OBSINF"
        )

    model_name = os.getenv(
        "OPENAI_MODEL", "openai/gpt-5-mini"
    ).strip()

    if not model_name.startswith("openai/"):
        raise ValueError(
            "Para esta prueba OPENAI_MODEL debe comenzar con openai/"
        )

    return AgentConfiguration(
        agent_name="weblogic_specialist",
        model_name=model_name,
        instruction=load_weblogic_instruction(),
    )


def parse_agent_response(
    response_text: str,
    *,
    resource_key: str,
    evidence: list[dict[str, Any]],
    event_context: EventContext | None = None,
) -> FindingProposal:
    """Valida la estructura y las referencias del hallazgo propuesto."""
    try:
        proposal = FindingProposal.model_validate_json(response_text)
    except ValueError as exc:
        raise ValueError(
            "El agente no devolvió un hallazgo JSON válido"
        ) from exc

    periods = {
        item["id"]: (
            datetime.fromisoformat(item["start_at"]),
            datetime.fromisoformat(item["end_at"]),
        )
        for item in evidence
    }

    validate_finding_context(
        proposal,
        expected_resource=resource_key,
        allowed_evidence_ids=set(periods),
        evidence_periods=periods,
    )

    validate_event_citations(proposal, event_context)
    return proposal


async def analyze_resource(
    resource_key: str,
    evidence: list[dict[str, Any]],
    configuration: AgentConfiguration,
    *,
    event_context: EventContext | None = None,
) -> FindingProposal:
    """Invoca al especialista para un recurso y valida su respuesta."""
    message_text = build_weblogic_message(
        resource_key, evidence, event_context=event_context
    )
    response_text = await run_specialist(
        message_text,
        configuration,
        description="Interpreta evidencias deterministas de Oracle WebLogic.",
    )

    return parse_agent_response(
        response_text,
        resource_key=resource_key,
        evidence=evidence,
        event_context=event_context,
    )
