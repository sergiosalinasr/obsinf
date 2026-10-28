"""Aplica y consulta migraciones Alembic en la base obsinf_test.

Uso desde la raíz de obsinf:

    python scripts/migrate_test_db.py
    python scripts/migrate_test_db.py --current
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values
from sqlalchemy.engine import make_url


# La raíz es el directorio que contiene scripts/.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_ENV_FILE = PROJECT_ROOT / ".env.test"
EXPECTED_DATABASE = "obsinf_test"


def load_test_environment() -> dict[str, str]:
    """Carga y valida la configuración antes de ejecutar Alembic."""
    if not TEST_ENV_FILE.is_file():
        raise RuntimeError(f"No se encontró {TEST_ENV_FILE.name}")

    config = dotenv_values(TEST_ENV_FILE)
    database_url = config.get("OBSINF_DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "Falta OBSINF_DATABASE_URL en .env.test"
        )

    try:
        url = make_url(database_url)
    except Exception as exc:
        raise RuntimeError(
            "OBSINF_DATABASE_URL no tiene un formato válido"
        ) from exc

    if (
        url.get_backend_name() != "postgresql"
        or url.database != EXPECTED_DATABASE
    ):
        raise RuntimeError(
            f"Se requiere PostgreSQL y la base {EXPECTED_DATABASE}"
        )

    # Informamos el destino ocultando la contraseña.
    print(
        f"Destino: {url.render_as_string(hide_password=True)}",
        flush=True,
    )

    # La configuración de prueba prevalece sobre el entorno actual.
    test_env = os.environ.copy()
    test_env.update({
        key: value
        for key, value in config.items()
        if value is not None
    })

    return test_env


def run_alembic(arguments: list[str], env: dict[str, str]) -> None:
    """Ejecuta Alembic desde la raíz del proyecto."""
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Administrar migraciones de obsinf_test"
    )
    parser.add_argument(
        "--current",
        action="store_true",
        help="Solo mostrar la revisión actual, sin aplicar cambios",
    )
    args = parser.parse_args()

    try:
        test_env = load_test_environment()

        if not args.current:
            print("Aplicando migraciones pendientes...", flush=True)
            run_alembic(["upgrade", "head"], test_env)

        print("Revisión actual:", flush=True)
        run_alembic(["current"], test_env)

        return 0

    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())