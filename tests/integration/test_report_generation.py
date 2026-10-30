"""Selección y generación de reportes sin invocar modelos externos."""

from copy import deepcopy
from datetime import timedelta

import pytest
from pydantic import ValidationError

from test_correlations import prepare, save
from test_dependency_context import joint_context
from test_oracle_findings import oracle_contexts

from app.schemas.report import ReportRequest
from app.services.report_markdown import render_report_markdown
from app.services.report_selection import (
    ReportSelectionError,
    select_report_data,
)


@pytest.fixture
def report_case(db_session, joint_context):
    context, proposal, configuration = prepare(
        db_session, joint_context
    )
    correlation = save(
        db_session, joint_context, context, proposal, configuration
    )
    execution = joint_context["oracle"]["execution"]

    request = ReportRequest(
        period_start=execution.period_start,
        period_end=execution.period_end,
        timezone="America/Santiago",
        correlation_ids=[correlation.id],
    )
    return joint_context, correlation, request


def select(db, case, **changes):
    joint, _, request = case
    values = {
        "company_id": joint["company_id"],
        "request": request,
    }
    values.update(changes)
    return select_report_data(db, **values)


def test_correlation_includes_both_findings(db_session, report_case):
    joint, correlation, _ = report_case
    data = select(db_session, report_case)

    assert {row["id"] for row in data["findings"]} == {
        joint["consumer"].id,
        joint["provider"].id,
    }
    assert [row["id"] for row in data["correlations"]] == [correlation.id]


def test_explicit_and_implicit_finding_is_not_duplicated(
    db_session, report_case
):
    joint, _, request = report_case
    values = request.model_dump()
    values["finding_ids"] = [joint["consumer"].id]

    data = select(
        db_session,
        report_case,
        request=ReportRequest.model_validate(values),
    )
    assert len(data["findings"]) == 2


def test_foreign_company_cannot_select_correlation(
    db_session, report_case, oracle_contexts
):
    with pytest.raises(ReportSelectionError) as caught:
        select(
            db_session,
            report_case,
            company_id=oracle_contexts[1]["company"].id,
        )

    assert caught.value.code == "CORRELATION_NOT_FOUND"


def test_foreign_finding_is_rejected(
    db_session, report_case, oracle_contexts
):
    from test_oracle_findings import persist

    foreign = persist(db_session, oracle_contexts[1])
    _, _, request = report_case
    values = request.model_dump()
    values["finding_ids"] = [foreign.id]

    with pytest.raises(ReportSelectionError) as caught:
        select(
            db_session,
            report_case,
            request=ReportRequest.model_validate(values),
        )

    assert caught.value.code == "FINDING_NOT_FOUND"


def test_execution_must_cover_requested_period(db_session, report_case):
    _, _, request = report_case
    values = request.model_dump()
    values["period_start"] -= timedelta(minutes=1)

    with pytest.raises(ReportSelectionError) as caught:
        select(
            db_session,
            report_case,
            request=ReportRequest.model_validate(values),
        )

    assert caught.value.code == "INCOMPATIBLE_PERIOD"


def test_finding_must_fit_requested_period(db_session, report_case):
    joint, _, request = report_case
    values = request.model_dump()
    values["period_start"] = (
        joint["provider"].start_at + timedelta(seconds=1)
    )

    with pytest.raises(ReportSelectionError) as caught:
        select(
            db_session,
            report_case,
            request=ReportRequest.model_validate(values),
        )

    assert caught.value.code == "INCOMPATIBLE_PERIOD"


def test_markdown_is_deterministic(db_session, report_case):
    data = select(db_session, report_case)
    original = deepcopy(data)

    first = render_report_markdown(data)
    second = render_report_markdown(deepcopy(data))

    assert first == second
    assert data == original
    assert "NOT\\_ESTABLISHED" in first
    assert "America/Santiago" in first
    assert "-03:00" in first


def test_partial_coverage_is_visible(db_session, report_case):
    joint, _, _ = report_case
    joint["oracle"]["execution"].status = "partial"
    db_session.flush()

    data = select(db_session, report_case)
    markdown = render_report_markdown(data)

    assert "Cobertura parcial" in markdown


def test_external_text_is_escaped(db_session, report_case):
    data = select(db_session, report_case)
    data["findings"][0]["finding"] = (
        "<script>alert(1)</script> [enlace](https://example.com)"
    )

    markdown = render_report_markdown(data)

    assert "<script>" not in markdown
    assert "[enlace](https://example.com)" not in markdown
    assert "&lt;script&gt;" in markdown


@pytest.mark.parametrize(
    "changes",
    [
        {"timezone": "Zona/Inexistente"},
        {"finding_ids": [True]},
        {"finding_ids": [1, 1]},
        {"correlation_ids": [], "finding_ids": []},
        {"period_start": "2026-10-27T12:00:00"},
    ],
)
def test_invalid_request(report_case, changes):
    _, _, request = report_case
    values = request.model_dump()
    values.update(changes)

    with pytest.raises(ValidationError):
        ReportRequest.model_validate(values)