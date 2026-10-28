from uuid import uuid4

from app.models.technology import Technology


def test_list_seeded_weblogic(client):
    """Comprueba que la migración incorporó WebLogic al catálogo."""
    response = client.get("/api/v1/technologies")

    assert response.status_code == 200, response.text

    technologies = response.json()
    weblogic = next(
        (item for item in technologies if item["code"] == "weblogic"),
        None,
    )

    assert weblogic is not None
    assert weblogic["name"] == "Oracle WebLogic Server"
    assert weblogic["is_active"] is True


def test_filter_inactive_technologies(client, db_session):
    """Excluye tecnologías inactivas salvo petición explícita."""
    code = f"test_{uuid4().hex[:12]}"

    technology = Technology(
        code=code,
        name="Tecnología inactiva de prueba",
        is_active=False,
    )
    db_session.add(technology)
    db_session.flush()

    # Por defecto, la tecnología inactiva no debe aparecer.
    response = client.get("/api/v1/technologies")
    assert response.status_code == 200

    assert code not in {item["code"] for item in response.json()}

    # Al desactivar el filtro, debe aparecer y conservar su estado.
    response = client.get(
        "/api/v1/technologies",
        params={"active_only": False},
    )
    assert response.status_code == 200

    item = next(
        item for item in response.json()
        if item["code"] == code
    )
    assert item["is_active"] is False


def test_technologies_ordered_by_code(client):
    """El catálogo mantiene un orden predecible."""
    response = client.get(
        "/api/v1/technologies",
        params={"active_only": False},
    )

    assert response.status_code == 200

    codes = [item["code"] for item in response.json()]
    assert codes == sorted(codes)