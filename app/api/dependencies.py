from fastapi import HTTPException, status

from app.core.config import get_settings


def require_local_dev() -> None:
    """Permite acceso únicamente en el modo local de desarrollo.

    Este control se reemplazará por autorización de usuarios
    cuando incorporemos autenticación.
    """
    settings = get_settings()

    if settings.env != "local" or not settings.local_dev_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCESS_NOT_CONFIGURED",
                "message": "Este endpoint requiere autorización configurada",
            },
        )