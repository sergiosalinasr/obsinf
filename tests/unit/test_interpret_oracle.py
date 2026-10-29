"""Comando Oracle simulado: modo de prueba, persistencia y prevalidación."""

import asyncio
from types import SimpleNamespace

import pytest

from app.agents.specialist_runtime import AgentConfiguration
from app.analysis.finding_contract import FindingProposal
from app.jobs import interpret_oracle


def evidence():
    return [{
        "id": 7, "resource_key": "ORCLPDB1/ERP_SERVICE",
        "metric_name": "oracle_blocked_sessions", "unit": "count",
        "start_at": "2026-10-27T12:02:00Z", "end_at": "2026-10-27T12:04:00Z",
    }]


def proposal():
    return FindingProposal.model_validate({
        "resource_key": "ORCLPDB1/ERP_SERVICE", "start": "2026-10-27T12:02:00Z",
        "end": "2026-10-27T12:04:00Z", "classification": "ANOMALY", "severity": "LOW",
        "confidence": 0.7, "finding": "Tres muestras de sesiones bloqueadas fuera del perfil.",
        "evidence_ids": [7], "event_ids": [], "possible_implications": [],
    })


class FakeSession:
    active = 0
    def __enter__(self):
        FakeSession.active += 1
        return self
    def __exit__(self, *args):
        FakeSession.active -= 1
        return False


def setup(monkeypatch):
    calls = {"saved": [], "analyzed": [], "checked": []}
    config = AgentConfiguration("oracle_specialist", "openai/test", "Prompt Oracle exacto")
    monkeypatch.setattr(interpret_oracle, "load_evidence", lambda *args: (evidence(), "completed"))
    monkeypatch.setattr(interpret_oracle, "load_agent_configuration", lambda: config)
    monkeypatch.setattr(interpret_oracle, "SessionLocal", FakeSession)
    monkeypatch.setattr(interpret_oracle, "ensure_can_persist", lambda *args: calls["checked"].append(args))
    async def analyze(resource_key, items, configuration):
        assert FakeSession.active == 0
        assert resource_key == "ORCLPDB1/ERP_SERVICE"
        assert items == evidence()
        assert configuration is config
        calls["analyzed"].append(resource_key)
        return proposal()
    def save(db, **kwargs):
        assert FakeSession.active == 1
        calls["saved"].append(kwargs)
        return SimpleNamespace(id=42)
    monkeypatch.setattr(interpret_oracle, "analyze_resource", analyze)
    monkeypatch.setattr(interpret_oracle, "save_finding", save)
    return calls, config


def test_dry_run_does_not_save(monkeypatch, capsys):
    calls, _ = setup(monkeypatch)
    assert asyncio.run(interpret_oracle.run(1, 4, 4)) == 0
    assert len(calls["analyzed"]) == 1
    assert calls["saved"] == calls["checked"] == []
    assert "no se guardaron" in capsys.readouterr().out


def test_persist_passes_oracle_context_and_exact_configuration(monkeypatch, capsys):
    calls, config = setup(monkeypatch)
    assert asyncio.run(interpret_oracle.run(1, 4, 4, persist=True)) == 0
    assert calls["checked"] == [(1, 4, 4, "ORCLPDB1/ERP_SERVICE", "oracle_specialist")]
    assert len(calls["saved"]) == 1
    saved = calls["saved"][0]
    assert saved["expected_technology"] == "oracle"
    assert saved["company_id"] == 1 and saved["execution_id"] == 4 and saved["source_id"] == 4
    assert saved["model_name"] == config.model_name
    assert saved["instruction"] == config.instruction
    assert saved["proposal"].event_ids == []
    assert "ID: 42" in capsys.readouterr().out


def test_empty_evidence_skips_configuration_and_model(monkeypatch, capsys):
    calls, _ = setup(monkeypatch)
    monkeypatch.setattr(interpret_oracle, "load_evidence", lambda *args: ([], "completed"))
    def forbidden():
        raise AssertionError("No debe configurar el agente sin evidencias")
    monkeypatch.setattr(interpret_oracle, "load_agent_configuration", forbidden)
    assert asyncio.run(interpret_oracle.run(1, 4, 4, persist=True)) == 0
    assert calls["saved"] == calls["analyzed"] == calls["checked"] == []
    assert "no se invocará" in capsys.readouterr().out


def test_existing_finding_stops_before_model_call(monkeypatch):
    calls, _ = setup(monkeypatch)
    def duplicate(*args):
        raise ValueError("Ya existe el hallazgo")
    monkeypatch.setattr(interpret_oracle, "ensure_can_persist", duplicate)
    with pytest.raises(ValueError, match="Ya existe"):
        asyncio.run(interpret_oracle.run(1, 4, 4, persist=True))
    assert calls["analyzed"] == calls["saved"] == []


def test_partial_analysis_prints_coverage_notice(monkeypatch, capsys):
    setup(monkeypatch)
    monkeypatch.setattr(interpret_oracle, "load_evidence", lambda *args: (evidence(), "partial"))
    assert asyncio.run(interpret_oracle.run(1, 4, 4)) == 0
    assert "Cobertura parcial" in capsys.readouterr().out
