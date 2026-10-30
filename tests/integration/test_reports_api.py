"""Consultas y descarga de reportes sin regeneración ni LLM."""

import pytest

from test_report_generation import report_case
from test_dependency_context import joint_context
from test_oracle_findings import oracle_contexts

from app.schemas.report import ReportRequest
from app.services.reports import create_report


@pytest.fixture
def saved_report(db_session, report_case):
    joint, _, request = report_case
    return create_report(
        db_session,
        company_id=joint["company_id"],
        request=request,
    )


def base_url(company_id):
    return f"/api/v1/companies/{company_id}/reports"


def test_list_reports(client, saved_report):
    row = saved_report
    response = client.get(base_url(row.company_id))

    assert response.status_code == 200
    items = response.json()
    assert [item["id"] for item in items] == [row.id]
    assert items[0]["generator_version"] == row.generator_version
    assert "content_markdown" not in items[0]
    assert "selection_snapshot" not in items[0]


def test_report_detail(client, saved_report):
    row = saved_report
    response = client.get(
        f"{base_url(row.company_id)}/{row.id}"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["content_markdown"] == row.content_markdown
    assert data["request_sha256"] == row.request_sha256
    assert "selection_snapshot" not in data


def test_download_exact_markdown(client, saved_report):
    row = saved_report
    response = client.get(
        f"{base_url(row.company_id)}/{row.id}/markdown"
    )

    assert response.status_code == 200
    assert response.content == row.content_markdown.encode("utf-8")
    assert response.headers["content-type"].startswith("text/markdown")
    assert "charset=utf-8" in response.headers["content-type"]
    assert response.headers["content-disposition"] == (
        f'attachment; filename="obsinf_company_{row.company_id}'
        f'_report_{row.id}.md"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_queries_do_not_regenerate(
    client, saved_report, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("Las consultas no deben regenerar el reporte")

    monkeypatch.setattr(
        "app.services.reports.render_report_markdown",
        forbidden,
    )
    row = saved_report
    base = base_url(row.company_id)

    assert client.get(base).status_code == 200
    assert client.get(f"{base}/{row.id}").status_code == 200
    assert client.get(f"{base}/{row.id}/markdown").status_code == 200


def test_other_company_cannot_read(
    client, saved_report, oracle_contexts
):
    other_company_id = oracle_contexts[1]["company"].id
    base = base_url(other_company_id)

    assert client.get(base).json() == []

    for suffix in ("", "/markdown"):
        response = client.get(
            f"{base}/{saved_report.id}{suffix}"
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "REPORT_NOT_FOUND"


def test_missing_report(client, saved_report):
    base = base_url(saved_report.company_id)

    for suffix in ("", "/markdown"):
        response = client.get(
            f"{base}/{saved_report.id + 1}{suffix}"
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "REPORT_NOT_FOUND"


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 1001},
        {"after_id": -1},
    ],
)
def test_invalid_pagination(client, saved_report, params):
    response = client.get(
        base_url(saved_report.company_id),
        params=params,
    )
    assert response.status_code == 422


def test_pagination(
    client, db_session, saved_report, report_case
):
    joint, _, request = report_case
    values = request.model_dump()
    values["timezone"] = "UTC"

    second = create_report(
        db_session,
        company_id=joint["company_id"],
        request=ReportRequest.model_validate(values),
    )
    base = base_url(saved_report.company_id)

    first_page = client.get(base, params={"limit": 1})
    assert [item["id"] for item in first_page.json()] == [
        saved_report.id
    ]

    next_page = client.get(
        base,
        params={"after_id": saved_report.id, "limit": 1},
    )
    assert [item["id"] for item in next_page.json()] == [second.id]


def test_inactive_company_can_read_history(
    client, db_session, saved_report, report_case
):
    joint, _, _ = report_case
    joint["oracle"]["company"].is_active = False
    db_session.flush()

    base = base_url(saved_report.company_id)
    assert client.get(base).status_code == 200
    assert client.get(f"{base}/{saved_report.id}").status_code == 200
    assert client.get(
        f"{base}/{saved_report.id}/markdown"
    ).status_code == 200