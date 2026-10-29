"""Pruebas del adaptador ADK con un runner simulado y sin red."""

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.agents.specialist_runtime import AgentConfiguration, run_specialist


def install_fake_adk(monkeypatch, events):
    calls = {"sessions": [], "runs": []}
    for name in ["google", "google.adk", "google.adk.agents", "google.adk.models", "google.adk.models.lite_llm", "google.adk.runners", "google.genai", "google.genai.types"]:
        module = ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)

    def agent(**kwargs):
        calls["agent"] = kwargs
        return SimpleNamespace(**kwargs)

    class Sessions:
        async def create_session(self, **kwargs):
            calls["sessions"].append(kwargs)
            return SimpleNamespace(id="test-session")

    class Runner:
        def __init__(self, **kwargs):
            self.session_service = Sessions()
            calls["runner"] = kwargs
        async def run_async(self, **kwargs):
            calls["runs"].append(kwargs)
            for event in events:
                yield event

    sys.modules["google.adk.agents"].LlmAgent = agent
    sys.modules["google.adk.models.lite_llm"].LiteLlm = lambda **kwargs: SimpleNamespace(**kwargs)
    sys.modules["google.adk.runners"].InMemoryRunner = Runner
    types = sys.modules["google.genai.types"]
    types.Content = lambda **kwargs: SimpleNamespace(**kwargs)
    types.Part = SimpleNamespace(from_text=lambda **kwargs: SimpleNamespace(**kwargs))
    sys.modules["google.genai"].types = types
    return calls


def response(final, *parts):
    return SimpleNamespace(
        is_final_response=lambda: final,
        content=SimpleNamespace(parts=[SimpleNamespace(text=text) for text in parts]),
    )


def test_uses_only_final_response_and_exact_configuration(monkeypatch):
    calls = install_fake_adk(monkeypatch, [response(False, "ignorar"), response(True, '{"ok":', "true}")])
    config = AgentConfiguration("oracle_specialist", "openai/test", "Prompt exacto")
    result = asyncio.run(run_specialist("Datos autorizados", config, description="Oracle"))
    assert result == '{"ok":true}'
    assert calls["agent"]["name"] == config.agent_name
    assert calls["agent"]["instruction"] == config.instruction
    assert calls["agent"]["model"].model == config.model_name
    assert calls["runs"][0]["new_message"].parts[0].text == "Datos autorizados"
    assert calls["runner"]["app_name"] == "obsinf"


@pytest.mark.parametrize("events", [[], [response(False, "respuesta parcial")], [response(True, "")]])
def test_rejects_missing_final_text(monkeypatch, events):
    install_fake_adk(monkeypatch, events)
    with pytest.raises(RuntimeError, match="respuesta final"):
        asyncio.run(run_specialist("Datos", AgentConfiguration("test", "openai/test", "Prompt"), description="Test"))


def test_each_call_has_independent_user_session(monkeypatch):
    calls = install_fake_adk(monkeypatch, [response(True, "{}")])
    config = AgentConfiguration("test", "openai/test", "Prompt")
    for _ in range(2):
        asyncio.run(run_specialist("Datos", config, description="Test"))
    first, second = calls["sessions"]
    assert first["user_id"] != second["user_id"]
