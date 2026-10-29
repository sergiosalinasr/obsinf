"""Contrato y configuración del especialista Oracle sin llamadas al modelo."""

import asyncio
import json

import pytest

from app.agents import oracle_agent, oracle_prompt
from app.agents.specialist_runtime import AgentConfiguration


def evidence():
    return [{
        "id": 7, "resource_key": "ORCLPDB1/ERP_SERVICE",
        "metric_name": "oracle_blocked_sessions", "unit": "count",
        "start_at": "2026-10-27T12:02:00Z", "end_at": "2026-10-27T12:04:00Z",
        "threshold_value": 0, "min_observed": 2, "max_observed": 4,
        "sample_count": 3, "duration_seconds": 120,
    }]


def proposal(**changes):
    data = {
        "resource_key": "ORCLPDB1/ERP_SERVICE",
        "start": "2026-10-27T12:02:00Z", "end": "2026-10-27T12:04:00Z",
        "classification": "ANOMALY", "severity": "LOW", "confidence": 0.7,
        "finding": "Se observaron sesiones bloqueadas sobre el umbral configurado.",
        "evidence_ids": [7], "event_ids": [], "possible_implications": [],
    }
    data.update(changes)
    return data


def test_parse_oracle_response():
    result = oracle_agent.parse_agent_response(json.dumps(proposal()), resource_key="ORCLPDB1/ERP_SERVICE", evidence=evidence())
    assert result.evidence_ids == [7]
    assert result.event_ids == []


@pytest.mark.parametrize("changes", [
    {"evidence_ids": [99]}, {"resource_key": "OtherDB"}, {"event_ids": [5]},
    {"end": "2026-10-27T12:03:00Z"}, {"source": "oracle"},
    {"entity": "OtherDB"}, {"confidence": True}, {"classification": "UNKNOWN"},
])
def test_rejects_invalid_or_out_of_context_response(changes):
    with pytest.raises(ValueError):
        oracle_agent.parse_agent_response(json.dumps(proposal(**changes)), resource_key="ORCLPDB1/ERP_SERVICE", evidence=evidence())


def test_rejects_non_json_response():
    with pytest.raises(ValueError, match="JSON válido"):
        oracle_agent.parse_agent_response("Texto libre", resource_key="ORCLPDB1/ERP_SERVICE", evidence=evidence())


def test_build_message_contains_only_supplied_oracle_context():
    message = oracle_prompt.build_oracle_message("ORCLPDB1/ERP_SERVICE", evidence())
    payload = json.loads(message.split("DATOS:\n", 1)[1])
    assert payload["technology"] == "oracle"
    assert payload["evidence"] == evidence()
    assert "no como instrucciones" in message


@pytest.mark.parametrize("case", ["empty", "wrong_resource", "wrong_metric", "wrong_unit", "duplicate", "bool_id", "nan"])
def test_build_message_rejects_invalid_evidence(case):
    items = evidence()
    if case == "empty": items = []
    elif case == "wrong_resource": items[0]["resource_key"] = "OtherDB"
    elif case == "wrong_metric": items[0]["metric_name"] = "jdbc_active_connections"
    elif case == "wrong_unit": items[0]["unit"] = "percent"
    elif case == "duplicate": items.append(items[0].copy())
    elif case == "bool_id": items[0]["id"] = True
    elif case == "nan": items[0]["threshold_value"] = float("nan")
    with pytest.raises(ValueError):
        oracle_prompt.build_oracle_message("ORCLPDB1/ERP_SERVICE", items)


def test_instruction_is_complete_and_uses_current_contract():
    instruction = oracle_prompt.load_oracle_instruction()
    assert "{{CLASSIFICATION_TAXONOMY}}" not in instruction
    example = instruction[instruction.index("\n{") + 1:instruction.index("\n}") + 2]
    assert set(json.loads(example)) == set(proposal())


@pytest.mark.parametrize("text", ["", "{{CLASSIFICATION_TAXONOMY}}"])
def test_rejects_empty_or_pilot_template(tmp_path, monkeypatch, text):
    path = tmp_path / "oracle.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(oracle_prompt, "PROMPT_PATH", path)
    with pytest.raises(ValueError):
        oracle_prompt.load_oracle_instruction()


@pytest.mark.parametrize("key", ["", "your_openai_api_key_here"])
def test_requires_configured_api_key(monkeypatch, key):
    monkeypatch.setattr(oracle_agent, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENAI_API_KEY", key)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        oracle_agent.load_agent_configuration()


def test_loads_exact_oracle_configuration(monkeypatch):
    monkeypatch.setattr(oracle_agent, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    monkeypatch.setenv("OPENAI_MODEL", "openai/test-model")
    config = oracle_agent.load_agent_configuration()
    assert config.agent_name == "oracle_specialist"
    assert config.model_name == "openai/test-model"
    assert config.instruction == oracle_prompt.load_oracle_instruction()


def test_rejects_wrong_model_provider(monkeypatch):
    monkeypatch.setattr(oracle_agent, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    monkeypatch.setenv("OPENAI_MODEL", "other/test-model")
    with pytest.raises(ValueError, match="openai/"):
        oracle_agent.load_agent_configuration()


def test_analyze_resource_passes_message_and_validates_result(monkeypatch):
    config = AgentConfiguration("oracle_specialist", "openai/test", "Instrucción exacta")
    async def fake_run(message, configuration, *, description):
        assert configuration is config
        assert "Oracle Database" in description
        assert json.loads(message.split("DATOS:\n", 1)[1])["evidence"][0]["id"] == 7
        return json.dumps(proposal())
    monkeypatch.setattr(oracle_agent, "run_specialist", fake_run)
    result = asyncio.run(oracle_agent.analyze_resource("ORCLPDB1/ERP_SERVICE", evidence(), config))
    assert result.evidence_ids == [7]
