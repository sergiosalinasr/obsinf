import argparse
import json
import logging
from datetime import datetime

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.baseline_analysis import run_and_save_analysis


def parse_datetime(value: str) -> datetime:
    """Lee una fecha ISO 8601 y exige zona horaria."""
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "La fecha debe ser ISO 8601"
        ) from exc

    if result.tzinfo is None or result.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "La fecha debe incluir zona horaria"
        )

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analizar métricas con un perfil de normalidad"
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--profile-id", type=int, required=True)
    parser.add_argument("--from", dest="start", type=parse_datetime, required=True)
    parser.add_argument("--to", dest="end", type=parse_datetime, required=True)

    args = parser.parse_args()

    if args.company_id <= 0 or args.profile_id <= 0:
        parser.error("Los identificadores deben ser positivos")

    settings = get_settings()

    if settings.env != "local" or not settings.local_dev_mode:
        parser.error("Este comando inicial requiere modo local")

    print(
        f"Analizando empresa={args.company_id}, "
        f"perfil={args.profile_id}...",
        flush=True,
    )

    try:
        with SessionLocal() as db:
            result = run_and_save_analysis(
                db,
                company_id=args.company_id,
                profile_id=args.profile_id,
                period_start=args.start,
                period_end=args.end,
            )

        print(json.dumps(result, ensure_ascii=False, indent=2))

        # Señalamos cobertura incompleta también mediante el código de salida.
        if any(item["status"] != "analyzed" for item in result["coverage"]):
            return 2

        return 0

    except Exception:
        logging.exception("No fue posible ejecutar el análisis")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())