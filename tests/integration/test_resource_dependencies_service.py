"""Pruebas del servicio de dependencias sobre PostgreSQL."""

import pytest

# Importación explícita de la fixture compartida entre ambos archivos.
from test_resource_dependencies_integrity import dependency_context

from app.schemas.resource_dependency import DependencyCreate
from app.services.resource_dependencies import (
    DependencyError,
    create_dependency,
    get_dependency,
    list_dependencies,
    set_dependency_active,
)


def payload(context, **changes):
    """Construye una solicitud válida con fuentes de la empresa."""
    consumer, provider = context["sources"][0]
    values = {
        "consumer_source_id": consumer.id,
        "consumer_resource_key": "ManagedServer1",
        "provider_source_id": provider.id,
        "provider_resource_key": "ORCLPDB1/ERP_SERVICE",
        "description": "Dependencia sintética configurada para pruebas",
    }
    values.update(changes)
    return DependencyCreate(**values)


def create(db, context, **changes):
    return create_dependency(
        db,
        context["companies"][0].id,
        payload(context, **changes),
        configured_by="pytest",
    )


def test_create_and_get(db_session, dependency_context):
    dependency = create(db_session, dependency_context)

    saved = get_dependency(
        db_session, dependency.company_id, dependency.id
    )

    assert saved.id == dependency.id
    assert saved.configured_by == "pytest"
    assert saved.is_active is True


def test_duplicate(db_session, dependency_context):
    create(db_session, dependency_context)

    with pytest.raises(DependencyError) as caught:
        create(db_session, dependency_context)

    assert caught.value.code == "DEPENDENCY_EXISTS"


@pytest.mark.parametrize("source_position", [0, 1])
def test_inactive_source(
    db_session, dependency_context, source_position
):
    source = dependency_context["sources"][0][source_position]
    source.is_active = False
    db_session.flush()

    with pytest.raises(DependencyError) as caught:
        create(db_session, dependency_context)

    assert caught.value.code == "SOURCE_INACTIVE"


def test_inactive_company(db_session, dependency_context):
    dependency_context["companies"][0].is_active = False
    db_session.flush()

    with pytest.raises(DependencyError) as caught:
        create(db_session, dependency_context)

    assert caught.value.code == "COMPANY_INACTIVE"


@pytest.mark.parametrize(
    "field", ["consumer_source_id", "provider_source_id"]
)
def test_foreign_source(db_session, dependency_context, field):
    foreign = dependency_context["sources"][1][0]

    with pytest.raises(DependencyError) as caught:
        create(
            db_session,
            dependency_context,
            **{field: foreign.id},
        )

    assert caught.value.code == "SOURCE_NOT_FOUND"


def test_foreign_dependency_is_not_exposed(
    db_session, dependency_context
):
    dependency = create(db_session, dependency_context)
    other_company = dependency_context["companies"][1]

    with pytest.raises(DependencyError) as caught:
        get_dependency(db_session, other_company.id, dependency.id)

    assert caught.value.code == "DEPENDENCY_NOT_FOUND"
    assert list_dependencies(db_session, other_company.id) == []


def test_self_dependency(db_session, dependency_context):
    source = dependency_context["sources"][0][0]

    with pytest.raises(DependencyError) as caught:
        create(
            db_session,
            dependency_context,
            consumer_source_id=source.id,
            provider_source_id=source.id,
            consumer_resource_key="SAME",
            provider_resource_key="SAME",
        )

    assert caught.value.code == "SELF_DEPENDENCY"


def test_state_and_filters(db_session, dependency_context):
    dependency = create(db_session, dependency_context)
    company_id = dependency.company_id

    set_dependency_active(
        db_session, company_id, dependency.id, is_active=False
    )

    assert list_dependencies(
        db_session, company_id, is_active=True
    ) == []
    assert [
        item.id
        for item in list_dependencies(
            db_session, company_id, is_active=False
        )
    ] == [dependency.id]

    restored = set_dependency_active(
        db_session, company_id, dependency.id, is_active=True
    )
    assert restored.id == dependency.id
    assert restored.is_active is True


def test_reactivation_requires_active_source(
    db_session, dependency_context
):
    dependency = create(db_session, dependency_context)
    source = dependency_context["sources"][0][1]
    source.is_active = False
    db_session.flush()

    # Desactivar es posible aunque la fuente ya esté inactiva.
    set_dependency_active(
        db_session,
        dependency.company_id,
        dependency.id,
        is_active=False,
    )

    with pytest.raises(DependencyError) as caught:
        set_dependency_active(
            db_session,
            dependency.company_id,
            dependency.id,
            is_active=True,
        )

    assert caught.value.code == "SOURCE_INACTIVE"

    saved = get_dependency(
        db_session, dependency.company_id, dependency.id
    )
    assert saved.is_active is False


def test_pagination(db_session, dependency_context):
    first = create(db_session, dependency_context)
    second = create(
        db_session,
        dependency_context,
        provider_resource_key="OTHER_SERVICE",
    )

    page = list_dependencies(
        db_session, first.company_id, limit=1
    )
    following = list_dependencies(
        db_session, first.company_id, after_id=page[0].id, limit=1
    )

    assert [item.id for item in page] == [first.id]
    assert [item.id for item in following] == [second.id]