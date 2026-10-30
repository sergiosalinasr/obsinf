"""Pruebas HTTP de dependencias con PostgreSQL aislado por fixture."""

import pytest
from sqlalchemy import select

from test_resource_dependencies_integrity import dependency_context

from app.models.resource_dependency import ResourceDependency


def url(context, company_index=0):
    company_id = context["companies"][company_index].id
    return f"/api/v1/companies/{company_id}/dependencies"


def payload(context, **changes):
    consumer, provider = context["sources"][0]
    values = {
        "consumer_source_id": consumer.id,
        "consumer_resource_key": "ManagedServer1",
        "provider_source_id": provider.id,
        "provider_resource_key": "ORCLPDB1/ERP_SERVICE",
        "description": "Relación sintética para pruebas HTTP",
    }
    values.update(changes)
    return values


def create(client, context, **changes):
    response = client.post(
        url(context), json=payload(context, **changes)
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_dependency(client, db_session, dependency_context):
    data = create(client, dependency_context)

    assert data["configured_by"] == "local-dev"
    assert data["is_active"] is True
    assert data["dependency_type"] == "uses_database_service"

    saved = db_session.get(ResourceDependency, data["id"])
    assert saved.company_id == dependency_context["companies"][0].id


def test_detail_and_list(client, dependency_context):
    data = create(client, dependency_context)
    base = url(dependency_context)

    assert client.get(f"{base}/{data['id']}").json() == data

    response = client.get(base)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [data["id"]]


def test_duplicate(client, dependency_context):
    create(client, dependency_context)
    response = client.post(
        url(dependency_context), json=payload(dependency_context)
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DEPENDENCY_EXISTS"


def test_patch_and_filter(client, dependency_context):
    data = create(client, dependency_context)
    base = url(dependency_context)
    detail = f"{base}/{data['id']}"

    response = client.patch(detail, json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    assert client.get(base, params={"is_active": True}).json() == []
    inactive = client.get(base, params={"is_active": False}).json()
    assert [item["id"] for item in inactive] == [data["id"]]

    response = client.patch(detail, json={"is_active": True})
    assert response.status_code == 200
    assert response.json()["id"] == data["id"]
    assert response.json()["is_active"] is True


def test_pagination(client, dependency_context):
    first = create(client, dependency_context)
    second = create(
        client,
        dependency_context,
        provider_resource_key="OTHER_SERVICE",
    )
    base = url(dependency_context)

    page = client.get(base, params={"limit": 1})
    assert page.status_code == 200
    assert [item["id"] for item in page.json()] == [first["id"]]

    following = client.get(
        base, params={"after_id": first["id"], "limit": 1}
    )
    assert [item["id"] for item in following.json()] == [second["id"]]


def test_other_company_cannot_read_or_patch(
    client, dependency_context
):
    data = create(client, dependency_context)
    foreign_base = url(dependency_context, company_index=1)
    detail = f"{foreign_base}/{data['id']}"

    assert client.get(foreign_base).json() == []

    responses = [
        client.get(detail),
        client.patch(detail, json={"is_active": False}),
    ]
    for response in responses:
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "DEPENDENCY_NOT_FOUND"

    original = client.get(f"{url(dependency_context)}/{data['id']}")
    assert original.json()["is_active"] is True


@pytest.mark.parametrize(
    "field", ["consumer_source_id", "provider_source_id"]
)
def test_foreign_source(client, dependency_context, field):
    foreign = dependency_context["sources"][1][0]
    response = client.post(
        url(dependency_context),
        json=payload(dependency_context, **{field: foreign.id}),
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SOURCE_NOT_FOUND"


@pytest.mark.parametrize(
    "changes",
    [
        {"consumer_resource_key": ""},
        {"provider_resource_key": "  RESOURCE"},
        {"consumer_source_id": True},
        {"dependency_type": "unknown"},
        {"configured_by": "forged-user"},
    ],
)
def test_invalid_create_preserves_database(
    client, db_session, dependency_context, changes
):
    response = client.post(
        url(dependency_context),
        json=payload(dependency_context, **changes),
    )
    assert response.status_code == 422

    company_id = dependency_context["companies"][0].id
    assert db_session.scalar(
        select(ResourceDependency.id).where(
            ResourceDependency.company_id == company_id
        )
    ) is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"is_active": None},
        {"is_active": "false"},
        {"is_active": 0},
        {"is_active": False, "description": "No permitido"},
    ],
)
def test_invalid_patch_preserves_dependency(
    client, dependency_context, body
):
    data = create(client, dependency_context)
    detail = f"{url(dependency_context)}/{data['id']}"

    assert client.patch(detail, json=body).status_code == 422
    assert client.get(detail).json()["is_active"] is True


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 1001},
        {"after_id": -1},
        {"is_active": "unknown"},
    ],
)
def test_invalid_query(client, dependency_context, params):
    response = client.get(url(dependency_context), params=params)
    assert response.status_code == 422


def test_reactivation_rejects_inactive_source(
    client, db_session, dependency_context
):
    data = create(client, dependency_context)
    detail = f"{url(dependency_context)}/{data['id']}"

    assert client.patch(
        detail, json={"is_active": False}
    ).status_code == 200

    dependency_context["sources"][0][1].is_active = False
    db_session.flush()

    response = client.patch(detail, json={"is_active": True})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SOURCE_INACTIVE"
    assert client.get(detail).json()["is_active"] is False