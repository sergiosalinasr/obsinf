from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.company import Company


@pytest.fixture
def company_payload():
    """Genera un código distinto para evitar colisiones con datos existentes."""
    return {
        "code": f"test_{uuid4().hex[:12]}",
        "name": "Empresa de prueba",
        "timezone": "America/Santiago",
    }


def test_create_company(client, db_session, company_payload):
    """Comprueba respuesta HTTP y persistencia del registro."""
    response = client.post("/api/v1/companies", json=company_payload)

    assert response.status_code == 201, response.text

    data = response.json()

    assert data["code"] == company_payload["code"].upper()
    assert data["is_active"] is True

    # Consultamos PostgreSQL para comprobar que el registro fue guardado.
    db_session.expire_all()
    company = db_session.get(Company, data["id"])

    assert company is not None
    assert company.name == company_payload["name"]


def test_duplicate_company_code(client, company_payload):
    """Un código repetido, incluso con otra capitalización, devuelve 409."""
    first = client.post("/api/v1/companies", json=company_payload)
    assert first.status_code == 201, first.text

    duplicate = {
        **company_payload,
        "code": company_payload["code"].upper(),
    }

    response = client.post("/api/v1/companies", json=duplicate)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "COMPANY_CODE_EXISTS"

    # El rollback del conflicto no debe inutilizar la sesión.
    lookup = client.get(f"/api/v1/companies/{first.json()['id']}")
    assert lookup.status_code == 200


def test_get_company(client, company_payload):
    """Consulta por ID una empresa creada durante la prueba."""
    created = client.post("/api/v1/companies", json=company_payload)
    assert created.status_code == 201, created.text

    company_id = created.json()["id"]
    response = client.get(f"/api/v1/companies/{company_id}")

    assert response.status_code == 200
    assert response.json()["id"] == company_id
    assert response.json()["code"] == company_payload["code"].upper()


def test_patch_company(client, db_session, company_payload):
    """Modifica el nombre y conserva los campos inmutables."""
    created = client.post("/api/v1/companies", json=company_payload)
    assert created.status_code == 201, created.text

    original = created.json()
    company_id = original["id"]

    response = client.patch(
        f"/api/v1/companies/{company_id}",
        json={"name": "Empresa modificada"},
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["name"] == "Empresa modificada"
    assert data["code"] == original["code"]
    assert data["created_at"] == original["created_at"]
    assert data["updated_at"] is not None

    db_session.expire_all()
    company = db_session.get(Company, company_id)

    assert company.name == "Empresa modificada"


def test_deactivate_and_reactivate_company(client, company_payload):
    """Comprueba ambos cambios de estado a través del API."""
    created = client.post("/api/v1/companies", json=company_payload)
    assert created.status_code == 201, created.text

    company_id = created.json()["id"]

    for active in (False, True):
        response = client.patch(
            f"/api/v1/companies/{company_id}",
            json={"is_active": active},
        )

        assert response.status_code == 200, response.text
        assert response.json()["is_active"] is active


def test_company_not_found(client, db_session):
    """Comprueba 404 usando un ID que no existe en la base de pruebas."""
    missing_id = 9_000_000_000_000_000_000

    assert db_session.get(Company, missing_id) is None

    response = client.get(f"/api/v1/companies/{missing_id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "COMPANY_NOT_FOUND"

    response = client.patch(
        f"/api/v1/companies/{missing_id}",
        json={"name": "No existe"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"code": "OTRO"},
        {"name": None},
        {"timezone": "Zona/Inexistente"},
    ],
)
def test_invalid_patch_preserves_company(
    client,
    db_session,
    company_payload,
    changes,
):
    """Comprueba 422 y que los datos existentes no se modifiquen."""
    created = client.post("/api/v1/companies", json=company_payload)
    assert created.status_code == 201, created.text

    company_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/companies/{company_id}",
        json=changes,
    )

    assert response.status_code == 422

    db_session.expire_all()
    company = db_session.get(Company, company_id)

    assert company.name == company_payload["name"]
    assert company.code == company_payload["code"].upper()
    assert company.is_active is True