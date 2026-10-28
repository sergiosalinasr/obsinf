import argparse
import json
import logging

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.ingestion_processing import process_batch


def main() -> int:
    """Procesa un lote explícito desde la terminal."""
    parser = argparse.ArgumentParser(
        description="Procesar un lote de ingesta de OBSINF"
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--batch-id", type=int, required=True)
    args = parser.parse_args()

    if args.company_id <= 0 or args.batch_id <= 0:
        parser.error("Los identificadores deben ser positivos")

    settings = get_settings()

    if settings.env != "local" or not settings.local_dev_mode:
        parser.error(
            "Este comando inicial requiere el modo local de desarrollo"
        )

    print(
        f"Procesando empresa={args.company_id}, lote={args.batch_id}...",
        flush=True,
    )

    try:
        with SessionLocal() as db:
            result = process_batch(db, args.company_id, args.batch_id)

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] != "failed" else 1

    except Exception:
        logging.exception("No fue posible procesar el lote")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())