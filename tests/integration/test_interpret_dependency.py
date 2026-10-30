"""Orquestación del comando sin llamadas externas."""

import asyncio
import json
from contextlib import contextmanager

import pytest

from app.analysis.coordinator_contract import CorrelationProposal
from app.jobs import interpret_dependency as job


def test_closes_database_before_agent(monkeypatch, capsys):
    state = {"open": False}

    context = {
        "dependency": {"id": 1},
        "consumer": {"finding": {"id": 3}},
        "provider": {"finding": {"id": 4}},
        "comparison": {"same_data_cutoff": False},
    }

    @contextmanager
    def session():
        state["open"] = True
        try:
            yield object()
        finally:
            state["open"] = False

    def build_context(db, **kwargs):
        assert state["open"] is True
        assert kwargs["company_id"] == 1
        return context

    async def analyze(received, configuration):
        assert state["open"] is False
        assert received is context

        return CorrelationProposal(
            dependency_id=1,
            finding_ids=[3, 4],
            evidence_ids=[5, 7],
            event_ids=[],
            assessment="NO_TEMPORAL_COINCIDENCE",
            causality="NOT_ESTABLISHED",
            confidence=0.7,
            summary="Resumen de prueba.",
            evidence_overlaps=[],
            limitations=["Prueba sin interpretación real."],
        )

    monkeypatch.setattr(job, "SessionLocal", session)
    monkeypatch.setattr(job, "build_dependency_context", build_context)
    monkeypatch.setattr(job, "load_agent_configuration", lambda: object())
    monkeypatch.setattr(job, "analyze_dependency", analyze)

    assert asyncio.run(job.run(1, 1, 3, 4)) == 0

    output = capsys.readouterr().out
    assert "distintos cortes" in output
    assert "no se guardó" in output
    assert state["open"] is False


def test_invalid_context_does_not_call_agent(monkeypatch):
    def load_context(*args):
        raise ValueError("Contexto inválido")

    def unexpected_configuration():
        pytest.fail("No debe cargar el agente para un contexto inválido")

    monkeypatch.setattr(job, "load_context", load_context)
    monkeypatch.setattr(
        job, "load_agent_configuration", unexpected_configuration
    )

    with pytest.raises(ValueError, match="Contexto inválido"):
        asyncio.run(job.run(1, 1, 3, 4))