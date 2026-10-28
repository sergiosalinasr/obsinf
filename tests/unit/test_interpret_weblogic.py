import asyncio
from types import SimpleNamespace

from app.agents.weblogic_agent import AgentConfiguration
from app.analysis.finding_contract import FindingProposal
from app.jobs import interpret_weblogic


def evidence():
    return [{
        "id": 1,
        "resource_key": "ManagedServer1",
        "start_at": "2026-10-27T12:02:00+00:00",
        "end_at": "2026-10-27T12:03:00+00:00",
    }]


def proposal():
    return FindingProposal.model_validate({
        "resource_key": "ManagedServer1",
        "start": "2026-10-27T12:02:00Z",
        "end": "2026-10-27T12:03:00Z",
        "classification": "ANOMALY",
        "severity": "LOW",
        "confidence": 0.75,
        "finding": "Se observó una desviación del rango configurado.",
        "evidence_ids": [1],
        "possible_implications": [],
    })


class FakeSession:
    """Sesión mínima para verificar la llamada al servicio."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def setup_fakes(monkeypatch):
    configuration = AgentConfiguration(
        agent_name="weblogic_specialist",
        model_name="openai/test-model",
        instruction="Prompt exacto de la prueba",
    )
    calls = []

    monkeypatch.setattr(
        interpret_weblogic,
        "load_evidence",
        lambda *args: (evidence(), "completed"),
    )
    monkeypatch.setattr(
        interpret_weblogic,
        "load_agent_configuration",
        lambda: configuration,
    )
    monkeypatch.setattr(
        interpret_weblogic,
        "SessionLocal",
        FakeSession,
    )

    async def fake_analyze(resource_key, items, config):
        assert resource_key == "ManagedServer1"
        assert items == evidence()
        assert config is configuration
        return proposal()

    def fake_save(db, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(id=42)

    monkeypatch.setattr(
        interpret_weblogic,
        "analyze_resource",
        fake_analyze,
    )
    monkeypatch.setattr(
        interpret_weblogic,
        "save_finding",
        fake_save,
    )

    return configuration, calls


def test_dry_run_does_not_save(monkeypatch, capsys):
    _, calls = setup_fakes(monkeypatch)

    result = asyncio.run(
        interpret_weblogic.run(1, 2, 3)
    )

    assert result == 0
    assert calls == []
    assert "no se guardaron" in capsys.readouterr().out


def test_persist_passes_exact_agent_configuration(monkeypatch, capsys):
    configuration, calls = setup_fakes(monkeypatch)

    result = asyncio.run(
        interpret_weblogic.run(1, 2, 3, persist=True)
    )

    assert result == 0
    assert len(calls) == 1
    assert calls[0]["company_id"] == 1
    assert calls[0]["execution_id"] == 2
    assert calls[0]["source_id"] == 3
    assert calls[0]["model_name"] == configuration.model_name
    assert calls[0]["instruction"] == configuration.instruction
    assert calls[0]["proposal"].evidence_ids == [1]
    assert "ID: 42" in capsys.readouterr().out


def test_empty_evidence_does_not_call_agent(monkeypatch, capsys):
    _, calls = setup_fakes(monkeypatch)

    monkeypatch.setattr(
        interpret_weblogic,
        "load_evidence",
        lambda *args: ([], "completed"),
    )

    result = asyncio.run(
        interpret_weblogic.run(1, 2, 3, persist=True)
    )

    assert result == 0
    assert calls == []
    assert "no se invocará" in capsys.readouterr().out