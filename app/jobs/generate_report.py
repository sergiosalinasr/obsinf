"""Generación manual de reportes guardados, sin LLM."""

import argparse
import sys

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.schemas.report import ReportRequest
from app.services.reports import create_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generar y guardar un reporte de observabilidad"
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--from", dest="period_start", required=True)
    parser.add_argument("--to", dest="period_end", required=True)
    parser.add_argument("--timezone", default="America/Santiago")
    parser.add_argument("--finding-id", type=int, action="append", default=[])
    parser.add_argument(
        "--correlation-id", type=int, action="append", default=[]
    )
    args = parser.parse_args()

    if args.company_id <= 0:
        parser.error("El identificador de empresa debe ser positivo")

    settings = get_settings()
    if settings.env != "local" or not settings.local_dev_mode:
        parser.error("Esta ejecución requiere modo local habilitado")

    try:
        request = ReportRequest(
            period_start=args.period_start,
            period_end=args.period_end,
            timezone=args.timezone,
            finding_ids=args.finding_id,
            correlation_ids=args.correlation_id,
        )

        with SessionLocal() as db:
            report = create_report(
                db,
                company_id=args.company_id,
                request=request,
            )
            report_id = report.id
            content = report.content_markdown

        print(content)
        print(f"\nReporte disponible con ID: {report_id}")
        return 0

    except Exception as exc:
        print(
            f"No fue posible generar el reporte: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())