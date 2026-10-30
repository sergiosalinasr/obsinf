"""Generación y conservación de reportes deterministas."""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.report import Report
from app.schemas.report import ReportRequest
from app.services.report_markdown import (
    GENERATOR_VERSION,
    render_report_markdown,
)
from app.services.report_selection import (
    ReportSelectionError,
    select_report_data,
)


def create_report(
    db: Session,
    *,
    company_id: int,
    request: ReportRequest,
) -> Report:
    """Genera o recupera un reporte equivalente.

    Administra commit y rollback; requiere una sesión dedicada.
    Los datos de selección y el Markdown se conservan en la misma escritura.
    """
    request_hash = None

    try:
        if type(company_id) is not int or company_id <= 0:
            raise ReportSelectionError(
                "INVALID_COMPANY", "La empresa debe tener un ID positivo"
            )

        # Serializa la generación por empresa.
        company = db.scalar(
            select(Company)
            .where(Company.id == company_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if company is None:
            raise ReportSelectionError(
                "COMPANY_NOT_FOUND", "Empresa no encontrada"
            )

        # Normaliza orden e instantes para que el orden de los IDs o un
        # desplazamiento equivalente no generen reportes distintos.
        normalized = request.model_dump(mode="json")
        normalized["finding_ids"] = sorted(request.finding_ids)
        normalized["correlation_ids"] = sorted(request.correlation_ids)

        from datetime import timezone

        normalized["period_start"] = request.period_start.astimezone(
            timezone.utc
        ).isoformat()
        normalized["period_end"] = request.period_end.astimezone(
            timezone.utc
        ).isoformat()

        normalized_request = ReportRequest.model_validate(normalized)

        data = select_report_data(
            db,
            company_id=company_id,
            request=normalized_request,
        )

        identity = json.dumps(
            {
                "generator_version": GENERATOR_VERSION,
                "selection": data,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        request_hash = hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()

        existing = db.scalar(
            select(Report).where(
                Report.company_id == company_id,
                Report.request_sha256 == request_hash,
            )
        )
        if existing is not None:
            db.commit()
            return existing

        report = Report(
            company_id=company_id,
            period_start=normalized_request.period_start,
            period_end=normalized_request.period_end,
            timezone=normalized_request.timezone,
            selection_snapshot=data,
            content_markdown=render_report_markdown(data),
            generator_version=GENERATOR_VERSION,
            request_sha256=request_hash,
        )
        db.add(report)
        db.flush()
        db.refresh(report)
        db.commit()
        return report

    except IntegrityError as exc:
        db.rollback()
        diagnostic = getattr(exc.orig, "diag", None)

        if (
            request_hash is not None
            and getattr(exc.orig, "sqlstate", None) == "23505"
            and getattr(diagnostic, "constraint_name", None)
            == "uq_reports_company_request"
        ):
            existing = db.scalar(
                select(Report).where(
                    Report.company_id == company_id,
                    Report.request_sha256 == request_hash,
                )
            )
            if existing is not None:
                return existing
        raise

    except Exception:
        db.rollback()
        raise