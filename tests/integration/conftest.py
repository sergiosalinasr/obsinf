from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def test_engine():
    """Crea una conexión exclusiva a la base de pruebas."""
    config = dotenv_values(PROJECT_ROOT / ".env.test")
    database_url = config.get("OBSINF_DATABASE_URL")

    if not database_url:
        raise RuntimeError("Falta OBSINF_DATABASE_URL en .env.test")

    # Evita ejecutar estas pruebas sobre las bases de desarrollo o de la POC.
    url = make_url(database_url)

    if url.get_backend_name() != "postgresql" or url.database != "obsinf_test":
        raise RuntimeError("Las pruebas requieren PostgreSQL y obsinf_test")

    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )

    yield engine

    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    """Aísla cada prueba mediante una transacción externa."""
    with test_engine.connect() as connection:
        transaction = connection.begin()

        # Los commit del servicio liberan un SAVEPOINT, pero no confirman
        # la transacción externa que protege la prueba.
        with Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        ) as session:
            try:
                yield session
            finally:
                session.close()

                if transaction.is_active:
                    transaction.rollback()


@pytest.fixture
def client(db_session):
    """Sustituye la sesión del API por la sesión de pruebas."""
    settings = get_settings()

    if settings.env != "local" or not settings.local_dev_mode:
        raise RuntimeError("Estas pruebas requieren el modo local habilitado")

    def override_get_db():
        # El cierre y rollback los administra la fixture db_session.
        yield db_session

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)