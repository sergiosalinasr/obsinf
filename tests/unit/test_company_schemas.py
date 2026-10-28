import pytest
from pydantic import ValidationError

from app.schemas.company import CompanyUpdate


@pytest.mark.parametrize("is_active", [False, True])
def test_company_update_accepts_active_status(is_active):
    """Permite desactivar y reactivar una empresa."""
    payload = CompanyUpdate(is_active=is_active)

    assert payload.is_active is is_active
    assert payload.model_dump(exclude_unset=True) == {
        "is_active": is_active
    }


@pytest.mark.parametrize(
    "data",
    [
        {"code": "OTRO"},
        {"name": None},
        {},
        {"name": "   "},
        {"timezone": "Zona/Inexistente"},
        {"is_active": "false"},
    ],
)
def test_company_update_rejects_invalid_payload(data):
    """Rechaza campos no permitidos y valores inválidos."""
    with pytest.raises(ValidationError):
        CompanyUpdate.model_validate(data)


def test_company_update_normalizes_name():
    """Elimina espacios externos y modifica solo el campo enviado."""
    payload = CompanyUpdate(name="  Empresa actualizada  ")

    assert payload.model_dump(exclude_unset=True) == {
        "name": "Empresa actualizada"
    }