"""Especialista Oracle adaptado al contrato y las referencias de OBSINF."""

import os
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

from app.agents.oracle_prompt import (
    PROJECT_ROOT, build_oracle_message, load_oracle_instruction, validate_oracle_evidence,
)
from app.agents.specialist_runtime import AgentConfiguration, run_specialist
from app.analysis.finding_contract import FindingProposal, validate_finding_context


def load_agent_configuration() -> AgentConfiguration:
    """Usa el mismo .env de OBSINF; no carga la configuración del piloto."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key == "your_openai_api_key_here":
        raise ValueError("Configura OPENAI_API_KEY en el .env de OBSINF")
    model_name = os.getenv("OPENAI_MODEL", "openai/gpt-5-mini").strip()
    if not model_name.startswith("openai/"):
        raise ValueError("Para esta prueba OPENAI_MODEL debe comenzar con openai/")
    return AgentConfiguration(
        agent_name="oracle_specialist", model_name=model_name,
        instruction=load_oracle_instruction(),
    )


def parse_agent_response(
    response_text: str, *, resource_key: str, evidence: list[dict[str, Any]]
) -> FindingProposal:
    validate_oracle_evidence(resource_key, evidence)
    try:
        proposal = FindingProposal.model_validate_json(response_text)
    except ValueError as exc:
        raise ValueError("El agente no devolvió un hallazgo JSON válido") from exc
    if proposal.event_ids:
        raise ValueError("El especialista Oracle no tiene eventos disponibles en esta etapa")
    periods = {
        item["id"]: (datetime.fromisoformat(item["start_at"]), datetime.fromisoformat(item["end_at"]))
        for item in evidence
    }
    validate_finding_context(
        proposal, expected_resource=resource_key,
        allowed_evidence_ids=set(periods), evidence_periods=periods,
    )
    return proposal


async def analyze_resource(
    resource_key: str, evidence: list[dict[str, Any]], configuration: AgentConfiguration
) -> FindingProposal:
    message_text = build_oracle_message(resource_key, evidence)
    response_text = await run_specialist(
        message_text, configuration,
        description="Interpreta evidencias deterministas de Oracle Database.",
    )
    return parse_agent_response(response_text, resource_key=resource_key, evidence=evidence)
