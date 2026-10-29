"""Integridad de las dependencias configuradas entre recursos."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.company import Company
from app.models.resource_dependency import ResourceDependency
from app.models.source import Source
from app.models.technology import Technology


@pytest.fixture
def dependency_context(db_session):
    """Prepara dos empresas y dos fuentes por empresa.

    No depende de IDs fijos ni modifica registros existentes.
    La transacción externa de db_session revierte los datos.
    """
    technology = db_session.scalar(
        select(Technology).where(Technology.code == "weblogic")
    )
    assert technology is not None, "Falta el catálogo WebLogic"

    companies = []
    sources = []

    for position in range(2):
        company = Company(
            code=f"DEP_{uuid4().hex[:12]}",
            name=f"Empresa de dependencias {position}",
        )
        db_session.add(company)
        db_session.flush()
        companies.append(company)

        company_sources = []

        for code in ("CONSUMER", "PROVIDER"):
            source = Source(
                company_id=company.id,
                technology_id=technology.id,
                code=code,
                name=f"Fuente {code}",
                source_timezone="America/Santiago",
            )
            db_session.add(source)
            company_sources.append(source)

        db_session.flush()
        sources.append(company_sources)

    return {"companies": companies, "sources": sources}


def dependency_values(context, company_index=0, **changes):
    """Construye una relación válida, permitiendo variar sus campos.

    Las fuentes usan la misma tecnología porque la integridad
    de esta tabla es independiente del adaptador.
    """
    company = context["companies"][company_index]
    consumer, provider = context["sources"][company_index]

    values = {
        "company_id": company.id,
        "consumer_source_id": consumer.id,
        "consumer_resource_key": "ManagedServer1",
        "provider_source_id": provider.id,
        "provider_resource_key": "ORCLPDB1/ERP_SERVICE",
        "dependency_type": "uses_database_service",
        "description": "Relación sintética para pruebas de integridad",
        "configured_by": "pytest",
    }
    values.update(changes)
    return values


def insert_dependency(db_session, values):
    """Inserta y fuerza la evaluación de restricciones."""
    dependency = ResourceDependency(**values)
    db_session.add(dependency)
    db_session.flush()
    return dependency


def assert_rejected(db_session, values, sqlstate):
    """Comprueba el tipo de rechazo sin invalidar la prueba completa.

    El SAVEPOINT revierte únicamente la operación inválida.
    Los códigos PostgreSQL distinguen CHECK, FK, UNIQUE y NOT NULL.
    """
    with pytest.raises(IntegrityError) as caught:
        with db_session.begin_nested():
            insert_dependency(db_session, values)

    assert caught.value.orig.sqlstate == sqlstate


def test_valid_dependency(db_session, dependency_context):
    """Guarda una relación y aplica los valores predeterminados."""
    dependency = insert_dependency(
        db_session,
        dependency_values(dependency_context),
    )
    db_session.refresh(dependency)

    assert dependency.id > 0
    assert dependency.is_active is True
    assert dependency.created_at is not None
    assert dependency.created_at.utcoffset() is not None
    assert dependency.updated_at is not None
    assert dependency.updated_at.utcoffset() is not None


def test_default_dependency_type(db_session, dependency_context):
    """El tipo inicial se completa desde el default de PostgreSQL."""
    values = dependency_values(dependency_context)
    values.pop("dependency_type")

    dependency = insert_dependency(db_session, values)
    db_session.refresh(dependency)

    assert dependency.dependency_type == "uses_database_service"


def test_duplicate_relationship(db_session, dependency_context):
    """La misma relación no puede registrarse dos veces."""
    values = dependency_values(dependency_context)
    insert_dependency(db_session, values)

    assert_rejected(db_session, values, "23505")


def test_inactive_relationship_still_prevents_duplicate(
    db_session, dependency_context
):
    """Desactivar conserva la identidad de la relación."""
    values = dependency_values(dependency_context, is_active=False)
    insert_dependency(db_session, values)

    assert_rejected(
        db_session,
        dependency_values(dependency_context),
        "23505",
    )


def test_equivalent_relationship_in_other_company(
    db_session, dependency_context
):
    """Dos empresas pueden utilizar las mismas claves de recurso."""
    first = insert_dependency(
        db_session,
        dependency_values(dependency_context, company_index=0),
    )
    second = insert_dependency(
        db_session,
        dependency_values(dependency_context, company_index=1),
    )

    assert first.id != second.id
    assert first.company_id != second.company_id


@pytest.mark.parametrize(
    "field",
    ["consumer_source_id", "provider_source_id"],
)
def test_rejects_foreign_company_source(
    db_session, dependency_context, field
):
    """Ninguno de los extremos puede pertenecer a otra empresa."""
    foreign_source = dependency_context["sources"][1][0]
    values = dependency_values(
        dependency_context,
        **{field: foreign_source.id},
    )

    assert_rejected(db_session, values, "23503")


@pytest.mark.parametrize(
    "field",
    ["consumer_source_id", "provider_source_id"],
)
def test_rejects_missing_source(
    db_session, dependency_context, field
):
    """Rechaza fuentes inexistentes; las identidades válidas son positivas."""
    values = dependency_values(
        dependency_context,
        **{field: -1},
    )

    assert_rejected(db_session, values, "23503")


def test_rejects_wrong_company(db_session, dependency_context):
    """No permite asignar fuentes válidas a una empresa diferente."""
    other_company = dependency_context["companies"][1]
    values = dependency_values(
        dependency_context,
        company_id=other_company.id,
    )

    assert_rejected(db_session, values, "23503")


def test_rejects_self_dependency(db_session, dependency_context):
    """Un recurso no puede ser consumidor y proveedor de sí mismo."""
    source = dependency_context["sources"][0][0]
    values = dependency_values(
        dependency_context,
        consumer_source_id=source.id,
        provider_source_id=source.id,
        consumer_resource_key="RESOURCE",
        provider_resource_key="RESOURCE",
    )

    assert_rejected(db_session, values, "23514")


def test_different_resources_in_same_source(
    db_session, dependency_context
):
    """Una fuente puede contener dos recursos relacionados."""
    source = dependency_context["sources"][0][0]
    dependency = insert_dependency(
        db_session,
        dependency_values(
            dependency_context,
            consumer_source_id=source.id,
            provider_source_id=source.id,
            consumer_resource_key="RESOURCE_A",
            provider_resource_key="RESOURCE_B",
        ),
    )

    assert dependency.id > 0


def test_same_resource_key_in_different_sources(
    db_session, dependency_context
):
    """La fuente forma parte de la identidad de cada recurso."""
    dependency = insert_dependency(
        db_session,
        dependency_values(
            dependency_context,
            consumer_resource_key="RESOURCE",
            provider_resource_key="RESOURCE",
        ),
    )

    assert dependency.id > 0


@pytest.mark.parametrize(
    "changes",
    [
        {"consumer_resource_key": ""},
        {"consumer_resource_key": "   "},
        {"provider_resource_key": ""},
        {"provider_resource_key": "   "},
        {"description": ""},
        {"description": "   "},
        {"configured_by": ""},
        {"configured_by": "   "},
        {"dependency_type": ""},
        {"dependency_type": "unknown"},
    ],
)
def test_rejects_invalid_values(
    db_session, dependency_context, changes
):
    """Comprueba los CHECK de texto y del tipo de dependencia."""
    values = dependency_values(dependency_context, **changes)

    assert_rejected(db_session, values, "23514")


@pytest.mark.parametrize(
    "field",
    [
        "company_id",
        "consumer_source_id",
        "consumer_resource_key",
        "provider_source_id",
        "provider_resource_key",
        "description",
        "configured_by",
    ],
)
def test_rejects_missing_required_value(
    db_session, dependency_context, field
):
    """Los campos obligatorios sin default no admiten NULL."""
    values = dependency_values(
        dependency_context,
        **{field: None},
    )

    assert_rejected(db_session, values, "23502")


def test_distinct_provider_resource(db_session, dependency_context):
    """Un consumidor puede utilizar más de un recurso proveedor."""
    first = insert_dependency(
        db_session,
        dependency_values(dependency_context),
    )
    second = insert_dependency(
        db_session,
        dependency_values(
            dependency_context,
            provider_resource_key="ORCLPDB1/OTHER_SERVICE",
        ),
    )

    assert first.id != second.id


def test_deactivate_and_reactivate(db_session, dependency_context):
    """Cambiar el estado conserva el registro y su identidad."""
    dependency = insert_dependency(
        db_session,
        dependency_values(dependency_context),
    )
    original_id = dependency.id

    dependency.is_active = False
    db_session.flush()
    db_session.refresh(dependency)
    assert dependency.is_active is False

    dependency.is_active = True
    db_session.flush()
    db_session.refresh(dependency)

    assert dependency.is_active is True
    assert dependency.id == original_id


@pytest.mark.parametrize("source_position", [0, 1])
def test_referenced_source_cannot_be_deleted(
    db_session, dependency_context, source_position
):
    """Las fuentes referenciadas se conservan sin borrado en cascada."""
    insert_dependency(
        db_session,
        dependency_values(dependency_context),
    )
    source = dependency_context["sources"][0][source_position]

    with pytest.raises(IntegrityError) as caught:
        with db_session.begin_nested():
            db_session.delete(source)
            db_session.flush()

    assert caught.value.orig.sqlstate == "23503"