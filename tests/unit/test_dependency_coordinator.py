"""Pruebas del coordinador sin llamar a ADK ni OpenAI."""

import asyncio
import json
from copy import deepcopy

import pytest

from test_coordinator_contract import context, payload

from app.agents import dependency_coordinator as coordinator
from app.agents.specialist_runtime import AgentConfiguration


def configuration():
    return AgentConfiguration(
        agent_name="dependency_coordinator",
        model_name="openai/test-model",
        instruction="Instrucción de prueba",
    )


def test_message_includes_expected_pairs(context):
    original = deepcopy(context)

    message = coordinator.build_coordinator_message(context)
    data = json.loads(message.split("\n", 1)[1])

    assert data["expected_evidence_overlaps"] == [
        {
            "consumer_evidence_id": 5,
            "provider_evidence_id": 7,
        }
    ]
    assert data["context"] == original
    assert context == original


def test_valid_runtime_response(monkeypatch, context, payload):
    async def fake_runtime(message, config, *, description):
        assert config.agent_name == "dependency_coordinator"
        assert description
        return json.dumps(payload)

    monkeypatch.setattr(
        coordinator, "run_specialist", fake_runtime
    )

    proposal = asyncio.run(
        coordinator.analyze_dependency(context, configuration())
    )

    assert proposal.finding_ids == [3, 4]
    assert proposal.causality == "NOT_ESTABLISHED"


def test_rejects_unauthorized_response(
    monkeypatch, context, payload
):
    payload["event_ids"] = [999]

    async def fake_runtime(*args, **kwargs):
        return json.dumps(payload)

    monkeypatch.setattr(
        coordinator, "run_specialist", fake_runtime
    )

    with pytest.raises(ValueError):
        asyncio.run(
            coordinator.analyze_dependency(context, configuration())
        )


def test_snapshot_survives_caller_mutation(
    monkeypatch, context, payload
):
    async def fake_runtime(*args, **kwargs):
        # Cambia el objeto original mientras la llamada está en curso.
        context["dependency"]["id"] = 999
        return json.dumps(payload)

    monkeypatch.setattr(
        coordinator, "run_specialist", fake_runtime
    )

    proposal = asyncio.run(
        coordinator.analyze_dependency(context, configuration())
    )
    assert proposal.dependency_id == 1


def test_rejects_wrong_agent(context):
    wrong = AgentConfiguration(
        agent_name="oracle_specialist",
        model_name="openai/test-model",
        instruction="Prueba",
    )

    with pytest.raises(ValueError, match="configuración"):
        asyncio.run(
            coordinator.analyze_dependency(context, wrong)
        )


def test_rejects_nonfinite_context(context):
    context["unexpected_number"] = float("nan")

    with pytest.raises(ValueError):
        coordinator.build_coordinator_message(context)


def test_rejects_oversized_context(monkeypatch, context):
    monkeypatch.setattr(coordinator, "MAX_MESSAGE_BYTES", 10)

    with pytest.raises(ValueError, match="tamaño"):
        coordinator.build_coordinator_message(context)


@pytest.mark.parametrize(
    "key,model",
    [
        ("", "openai/test-model"),
        ("your_openai_api_key_here", "openai/test-model"),
        ("test-key", "other/model"),
        ("test-key", "openai/"),
    ],
)
def test_rejects_invalid_configuration(
    monkeypatch, key, model
):
    monkeypatch.setattr(
        coordinator, "load_dotenv", lambda *args, **kwargs: None
    )
    monkeypatch.setenv("OPENAI_API_KEY", key)
    monkeypatch.setenv("OPENAI_MODEL", model)

    with pytest.raises(ValueError):
        coordinator.load_agent_configuration()


def test_loads_exact_instruction(monkeypatch, tmp_path):
    prompt = tmp_path / "prompt.txt"
    instruction = "Instrucción de prueba\n"
    prompt.write_text(instruction, encoding="utf-8")

    monkeypatch.setattr(coordinator, "PROMPT_PATH", prompt)
    monkeypatch.setattr(
        coordinator, "load_dotenv", lambda *args, **kwargs: None
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "openai/test-model")

    result = coordinator.load_agent_configuration()

    assert result.agent_name == "dependency_coordinator"
    assert result.instruction == instruction


def test_rejects_empty_instruction(monkeypatch, tmp_path):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("  \n", encoding="utf-8")

    monkeypatch.setattr(coordinator, "PROMPT_PATH", prompt)
    monkeypatch.setattr(
        coordinator, "load_dotenv", lambda *args, **kwargs: None
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "openai/test-model")

    with pytest.raises(ValueError, match="vacío"):
        coordinator.load_agent_configuration()