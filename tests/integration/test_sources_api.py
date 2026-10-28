from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.company import Company
from app.models.source import Source
from app.models.technology import Technology


@pytest.fixture
def source_context(db_session):
    """Prepara una empresa y obtiene WebLogic sin asumir su ID."""
    company = Company(
        code=f"TEST_{uuid4().hex[:12]}",
        name="Empresa de prueba de fuentes",
    )
    db_session.add(company)
    db_session.flush()

    technology = db_session.scalar(
        select(Technology).where(Technology.code == "weblogic")
    )
    assert technology is not None

    return company, technology


def source_payload(technology_id):
    """Construye una solicitud válida y reutilizable."""
    return {
        "technology_id": technology_id,
        "code": "wl_erp_prod",
        "name": "WebLogic ERP Producción",
        "environment": "production",
        "ingestion_method": "file",
        "source_timezone": "America/Santiago",
    }


def test_create_source(client, db_session, source_context):
    """Comprueba la respuesta y la empresa propietaria en PostgreSQL."""
    company, technology = source_context

    response = client.post(
        f"/api/v1/companies/{company.id}/sources",
        json=source_payload(technology.id),
    )

    assert response.status_code == 201, response.text
    data = response.json()

    assert data["company_id"] == company.id
    assert data["technology_id"] == technology.id
    assert data["code"] == "WL_ERP_PROD"
    assert data["is_active"] is True

    db_session.expire_all()
    saved = db_session.get(Source, data["id"])

    assert saved is not None
    assert saved.company_id == company.id


def test_duplicate_source_code(client, source_context):
    """Rechaza dos fuentes con el mismo código dentro de una empresa."""
    company, technology = source_context
    url = f"/api/v1/companies/{company.id}/sources"
    payload = source_payload(technology.id)

    assert client.post(url, json=payload).status_code == 201

    response = client.post(url, json=payload)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SOURCE_CODE_EXISTS"


def test_same_source_code_in_different_companies(
    client, db_session, source_context
):
    """Permite reutilizar un código en otra empresa."""
    company, technology = source_context

    other_company = Company(
        code=f"TEST_{uuid4().hex[:12]}",
        name="Otra empresa",
    )
    db_session.add(other_company)
    db_session.flush()

    payload = source_payload(technology.id)

    for company_id in (company.id, other_company.id):
        response = client.post(
            f"/api/v1/companies/{company_id}/sources",
            json=payload,
        )
        assert response.status_code == 201, response.text
        assert response.json()["company_id"] == company_id


@pytest.mark.parametrize("entity", ["company", "technology"])
def test_inactive_entity(client, db_session, source_context, entity):
    """Impide registrar fuentes con empresa o tecnología inactiva."""
    company, technology = source_context

    target = company if entity == "company" else technology
    target.is_active = False
    db_session.flush()

    response = client.post(
        f"/api/v1/companies/{company.id}/sources",
        json=source_payload(technology.id),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "COMPANY_INACTIVE" if entity == "company"
        else "TECHNOLOGY_INACTIVE"
    )


@pytest.mark.parametrize("entity", ["company", "technology"])
def test_missing_entity(client, db_session, source_context, entity):
    """Devuelve 404 si la empresa o la tecnología no existe."""
    company, technology = source_context
    missing_id = 9_000_000_000_000_000_000
    payload = source_payload(technology.id)

    if entity == "company":
        assert db_session.get(Company, missing_id) is None
        company_id = missing_id
        expected_code = "COMPANY_NOT_FOUND"
    else:
        assert db_session.get(Technology, missing_id) is None
        company_id = company.id
        payload["technology_id"] = missing_id
        expected_code = "TECHNOLOGY_NOT_FOUND"

    response = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json=payload,
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == expected_code


def test_unsupported_technology(client, db_session, source_context):
    """Estar activo en el catálogo no habilita cualquier tecnología."""
    company, _ = source_context

    technology = Technology(
        code=f"unsupported_{uuid4().hex[:12]}",
        name="Tecnología sin integración",
    )
    db_session.add(technology)
    db_session.flush()

    response = client.post(
        f"/api/v1/companies/{company.id}/sources",
        json=source_payload(technology.id),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TECHNOLOGY_NOT_SUPPORTED"


@pytest.mark.parametrize(
    "changes",
    [
        {"source_timezone": "Zona/Inexistente"},
        {"ingestion_method": "api"},
        {"code": "CON ESPACIOS"},
        {"name": "   "},
        {"company_id": 123},
    ],
)
def test_invalid_source_payload(client, source_context, changes):
    """Rechaza datos inválidos y empresas enviadas dentro del cuerpo."""
    company, technology = source_context
    payload = {**source_payload(technology.id), **changes}

    response = client.post(
        f"/api/v1/companies/{company.id}/sources",
        json=payload,
    )

    assert response.status_code == 422

def test_get_source(client, source_context):
    """Recupera una fuente de la empresa correcta."""
    company, technology = source_context

    created = client.post(
        f"/api/v1/companies/{company.id}/sources",
        json=source_payload(technology.id),
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]

    response = client.get(
        f"/api/v1/companies/{company.id}/sources/{source_id}"
    )

    assert response.status_code == 200
    assert response.json()["id"] == source_id
    assert response.json()["company_id"] == company.id


def test_sources_are_scoped_to_company(
    client, db_session, source_context
):
    """El listado y el detalle no devuelven fuentes de otra empresa."""
    company, technology = source_context

    created = client.post(
        f"/api/v1/companies/{company.id}/sources",
        json=source_payload(technology.id),
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]

    other_company = Company(
        code=f"TEST_{uuid4().hex[:12]}",
        name="Empresa sin fuentes",
    )
    db_session.add(other_company)
    db_session.flush()

    # La otra empresa existe, pero su listado debe estar vacío.
    response = client.get(
        f"/api/v1/companies/{other_company.id}/sources"
    )
    assert response.status_code == 200
    assert response.json() == []

    # Conocer el ID de una fuente ajena no permite consultarla.
    response = client.get(
        f"/api/v1/companies/{other_company.id}/sources/{source_id}"
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SOURCE_NOT_FOUND"


def test_sources_pagination(client, source_context):
    """Recorre dos fuentes sin repetirlas entre páginas."""
    company, technology = source_context
    url = f"/api/v1/companies/{company.id}/sources"
    source_ids = []

    for code in ("WL_FIRST", "WL_SECOND"):
        payload = {**source_payload(technology.id), "code": code}
        created = client.post(url, json=payload)
        assert created.status_code == 201, created.text
        source_ids.append(created.json()["id"])

    first = client.get(url, params={"limit": 1})
    assert first.status_code == 200
    assert [item["id"] for item in first.json()] == source_ids[:1]

    second = client.get(
        url,
        params={"limit": 1, "after_id": source_ids[0]},
    )
    assert second.status_code == 200
    assert [item["id"] for item in second.json()] == source_ids[1:]

    last = client.get(url, params={"after_id": source_ids[1]})
    assert last.status_code == 200
    assert last.json() == []


@pytest.mark.parametrize("detail", [False, True])
def test_sources_missing_company(client, db_session, detail):
    """Ambas consultas devuelven 404 si la empresa no existe."""
    missing_id = 9_000_000_000_000_000_000
    assert db_session.get(Company, missing_id) is None

    url = f"/api/v1/companies/{missing_id}/sources"
    if detail:
        url += "/1"

    response = client.get(url)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "COMPANY_NOT_FOUND"


def test_get_missing_source(client, db_session, source_context):
    """Devuelve 404 cuando la fuente no existe."""
    company, _ = source_context
    missing_id = 9_000_000_000_000_000_000
    assert db_session.get(Source, missing_id) is None

    response = client.get(
        f"/api/v1/companies/{company.id}/sources/{missing_id}"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SOURCE_NOT_FOUND"


def test_read_inactive_source_and_company(
    client, db_session, source_context
):
    """La desactivación conserva las consultas administrativas."""
    company, technology = source_context

    created = client.post(
        f"/api/v1/companies/{company.id}/sources",
        json=source_payload(technology.id),
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]

    source = db_session.get(Source, source_id)
    source.is_active = False
    company.is_active = False
    db_session.flush()

    response = client.get(
        f"/api/v1/companies/{company.id}/sources/{source_id}"
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    response = client.get(
        f"/api/v1/companies/{company.id}/sources"
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [source_id]


@pytest.mark.parametrize(
    "suffix",
    [
        "/sources?limit=0",
        "/sources?limit=1001",
        "/sources?after_id=-1",
        "/sources/0",
    ],
)

def test_invalid_source_query(client, source_context, suffix):
    """Valida límites de paginación e identificadores."""
    company, _ = source_context

    response = client.get(
        f"/api/v1/companies/{company.id}{suffix}"
    )

    assert response.status_code == 422