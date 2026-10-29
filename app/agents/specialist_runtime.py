"""Ejecución ADK compartida; cada especialista valida su propio contexto."""

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class AgentConfiguration:
    """Identidad, modelo e instrucción exactos usados en la interpretación."""

    agent_name: str
    model_name: str
    instruction: str


async def run_specialist(
    message_text: str,
    configuration: AgentConfiguration,
    *,
    description: str,
) -> str:
    """Invoca el modelo sin sesiones de BD y devuelve solo la respuesta final.

    Se conservan la integración ADK y la creación de sesiones independientes
    que ya utilizaba WebLogic. Las dependencias se cargan al invocar el modelo.
    """
    from google.adk.agents import LlmAgent
    from google.adk.models.lite_llm import LiteLlm
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    agent = LlmAgent(
        name=configuration.agent_name,
        model=LiteLlm(model=configuration.model_name),
        instruction=configuration.instruction,
        description=description,
    )
    runner = InMemoryRunner(agent=agent, app_name="obsinf")
    user_id = f"obsinf-local-{uuid4().hex}"
    session = await runner.session_service.create_session(app_name="obsinf", user_id=user_id)
    message = types.Content(role="user", parts=[types.Part.from_text(text=message_text)])
    response_text = None
    async for event in runner.run_async(
        user_id=user_id, session_id=session.id, new_message=message
    ):
        if event.is_final_response() and event.content:
            parts = event.content.parts or []
            text_parts = [part.text for part in parts if part.text]
            if text_parts:
                response_text = "".join(text_parts)
    if not response_text:
        raise RuntimeError("El agente no devolvió una respuesta final")
    return response_text
