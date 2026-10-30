"""Presentación y persistencia de reportes sin llamadas al LLM."""

from copy import deepcopy

import pytest
from sqlalchemy import func, select

from test_report_generation import report_case
from test_dependency_context import joint_context
from test_oracle_findings import oracle_contexts

from app.models.report import Report
from app.schemas.report import ReportRequest
from app.services.report_markdown import render_report_markdown
from app.services.report_selection import (
    ReportSelectionError,
    select_report_data,
)
from app.services.reports import create_report


def generate(db, case):
    joint, _, request = case
    return create_report(
        db,
        company_id=joint["company_id"],
        request=request,
    )


def test_saves_report_and_snapshot(db_session, report_case):
    report = generate(db_session, report_case)
    report_id = report.id

    db_session.expire_all()
    stored = db_session.get(Report, report_id)

    assert stored.generator_version == "observability_markdown:1.1.0"
    assert len(stored.request_sha256) == 64
    assert stored.content_markdown == render_report_markdown(
        stored.selection_snapshot
    )
    assert len(stored.selection_snapshot["findings"]) == 2


def test_repeated_request_returns_existing(db_session, report_case):
    first = generate(db_session, report_case)
    second = generate(db_session, report_case)

    assert first.id == second.id
    assert db_session.scalar(
        select(func.count()).select_from(Report).where(
            Report.company_id == first.company_id
        )
    ) == 1


def test_format_adjustments(db_session, report_case):
    joint, _, request = report_case
    data = select_report_data(
        db_session,
        company_id=joint["company_id"],
        request=request,
    )

    # Esta prueba verifica la tabla: necesita cobertura informada.
    data["executions"][0]["coverage"] = [
        {
            "rule_id": 1,
            "status": "analyzed",
            "samples": 8,
            "excluded_samples": 0,
            "evidence_count": 2,
        }
    ]

    markdown = render_report_markdown(data)

    assert "2 hallazgos y 1 correlación." in markdown
    assert "| Regla | Estado | Muestras | Excluidas | Evidencias |" in markdown
    assert "| 1 | analyzed | 8 | 0 | 2 |" in markdown
    assert "redacción original" in markdown
    assert "indican UTC" in markdown

    # Comprueba también la presentación cuando no existe cobertura.
    for execution in data["executions"]:
        execution["coverage"] = []

    markdown_without_coverage = render_report_markdown(data)

    assert "No se registró detalle de cobertura." in markdown_without_coverage
    assert "| Regla | Estado | Muestras | Excluidas | Evidencias |" not in (
        markdown_without_coverage
    )


def test_snapshot_survives_later_changes(db_session, report_case):
    report = generate(db_session, report_case)
    report_id = report.id
    original_snapshot = deepcopy(report.selection_snapshot)
    original_content = report.content_markdown

    joint, _, _ = report_case
    joint["dependency"].description = "Nueva descripción"
    db_session.flush()
    db_session.expire_all()

    stored = db_session.get(Report, report_id)
    assert stored.selection_snapshot == original_snapshot
    assert stored.content_markdown == original_content


def test_foreign_company_does_not_create_report(
    db_session, report_case, oracle_contexts
):
    _, _, request = report_case
    other_company_id = oracle_contexts[1]["company"].id

    with pytest.raises(ReportSelectionError):
        create_report(
            db_session,
            company_id=other_company_id,
            request=request,
        )

    assert db_session.scalar(
        select(func.count()).select_from(Report).where(
            Report.company_id == other_company_id
        )
    ) == 0


def test_equivalent_offsets_return_existing(db_session, report_case):
    joint, _, request = report_case
    first = generate(db_session, report_case)

    from datetime import timezone

    values = request.model_dump()
    values["period_start"] = request.period_start.astimezone(timezone.utc)
    values["period_end"] = request.period_end.astimezone(timezone.utc)

    second = create_report(
        db_session,
        company_id=joint["company_id"],
        request=ReportRequest.model_validate(values),
    )

    assert first.id == second.id