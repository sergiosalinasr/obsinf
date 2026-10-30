"""Consultas HTTP de correlaciones sin llamadas al modelo."""

import pytest

from test_correlations import prepare, save
from test_dependency_context import joint_context
from test_oracle_findings import oracle_contexts

from app.agents.specialist_runtime import AgentConfiguration


@pytest.fixture
def saved_correlation(db_session, joint_context):
    context, proposal, configuration = prepare(
        db_session, joint_context
    )
    return save(
        db_session,
        joint_context,
        context,
        proposal,
        configuration,
    )


def base_url(company_id):
    return f"/api/v1/companies/{company_id}/correlations"


def test_list(client, saved_correlation):
    row = saved_correlation
    response = client.get(base_url(row.company_id))

    assert response.status_code == 200
    items = response.json()
    assert [item["id"] for item in items] == [row.id]
    assert "context_snapshot" not in items[0]
    assert items[0]["proposal"]["causality"] == "NOT_ESTABLISHED"


def test_detail(client, saved_correlation):
    row = saved_correlation
    response = client.get(
        f"{base_url(row.company_id)}/{row.id}"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["context_snapshot"] == row.context_snapshot
    assert data["proposal"] == row.proposal
    assert data["prompt_sha256"] == row.prompt_sha256


def test_filter_dependency(client, saved_correlation):
    row = saved_correlation
    base = base_url(row.company_id)

    response = client.get(
        base, params={"dependency_id": row.dependency_id}
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [row.id]

    response = client.get(
        base, params={"dependency_id": row.dependency_id + 1}
    )
    assert response.status_code == 200
    assert response.json() == []


def test_other_company_cannot_read(
    client, saved_correlation, oracle_contexts
):
    row = saved_correlation
    other_company_id = oracle_contexts[1]["company"].id
    base = base_url(other_company_id)

    assert client.get(base).json() == []

    response = client.get(f"{base}/{row.id}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "CORRELATION_NOT_FOUND"


def test_missing_correlation(client, saved_correlation):
    row = saved_correlation
    response = client.get(
        f"{base_url(row.company_id)}/{row.id + 1}"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "CORRELATION_NOT_FOUND"


def test_pagination(client, db_session, joint_context, saved_correlation):
    context, proposal, configuration = prepare(
        db_session, joint_context
    )

    # Otro prompt representa una interpretación diferente.
    other_configuration = AgentConfiguration(
        agent_name=configuration.agent_name,
        model_name=configuration.model_name,
        instruction=configuration.instruction + "\nOtra versión",
    )
    second = save(
        db_session,
        joint_context,
        context,
        proposal,
        other_configuration,
    )

    base = base_url(saved_correlation.company_id)
    first_page = client.get(base, params={"limit": 1})

    assert first_page.status_code == 200
    assert [item["id"] for item in first_page.json()] == [
        saved_correlation.id
    ]

    following = client.get(
        base,
        params={"after_id": saved_correlation.id, "limit": 1},
    )
    assert [item["id"] for item in following.json()] == [second.id]


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 1001},
        {"after_id": -1},
        {"dependency_id": 0},
    ],
)
def test_invalid_query(client, saved_correlation, params):
    response = client.get(
        base_url(saved_correlation.company_id),
        params=params,
    )
    assert response.status_code == 422


def test_history_survives_dependency_deactivation(
    client, db_session, joint_context, saved_correlation
):
    joint_context["dependency"].is_active = False
    db_session.flush()

    row = saved_correlation
    response = client.get(
        f"{base_url(row.company_id)}/{row.id}"
    )

    assert response.status_code == 200
    # Se conserva el estado de la dependencia al interpretar.
    assert response.json()["context_snapshot"]["dependency"]["is_active"] is True