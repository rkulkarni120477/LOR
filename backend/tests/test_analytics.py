"""Analytics and reporting: reports, filters, drill-downs, exports (CSV, XLSX, PDF), scheduled
reports and their delivery."""

import io
import itertools
import re
import zipfile
from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree

from sqlalchemy import select

from app.db.models import ScheduledReport
from tests.conftest import build_package

_uploads = itertools.count()
ADMIN = {"roles": ["Super Administrator"]}


def hdr(token_factory, roles, sub):
    return {"Authorization": f"Bearer {token_factory(roles, sub=sub)}"}


def admin(token_factory, sub="root"):
    return hdr(token_factory, ["Super Administrator"], sub)


def author(token_factory):
    return hdr(token_factory, ["Contributor"], "author-1")


def upload(client, token_factory, title="Analytics item"):
    package = build_package(images=[(f"an-{next(_uploads)}.png", title)])
    response = client.post(
        "/api/v1/content",
        data={"title": title},
        files={"file": ("a.zip", package, "application/zip")},
        headers=author(token_factory),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def report(client, token_factory, name, **params):
    response = client.get(
        f"/api/v1/analytics/reports/{name}", params=params, headers=admin(token_factory)
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_reports_require_the_reporting_permission(client, token_factory):
    assert client.get("/api/v1/analytics/catalog", headers=author(token_factory)).status_code == 403
    catalog = client.get("/api/v1/analytics/catalog", headers=admin(token_factory)).json()
    assert {r["key"] for r in catalog["reports"]} == {
        "usage",
        "reuse",
        "growth",
        "workflow",
        "storage",
        "departments",
    }


def test_usage_counts_downloads_per_day_and_lists_top_items(client, token_factory):
    lo_id = upload(client, token_factory, title="Popular")
    for _ in range(2):
        assert (
            client.get(
                f"/api/v1/content/{lo_id}/download", headers=author(token_factory)
            ).status_code
            == 200
        )
    usage = report(client, token_factory, "usage")
    assert usage["summary"]["downloads"] == 2
    today = datetime.now(UTC).date().isoformat()
    row = next(r for r in usage["rows"] if r[0] == today)
    assert row[1] == 2
    assert usage["summary"]["top_items"][0][0] == "Popular"
    assert usage["chart"]["type"] == "line" and usage["chart"]["drill"] == "day"


def test_growth_and_workflow_reflect_submissions_and_approvals(client, token_factory):
    lo_id = upload(client, token_factory)
    client.post(f"/api/v1/workflow/{lo_id}/submit", headers=author(token_factory))
    client.post(
        f"/api/v1/workflow/{lo_id}/decision",
        json={"decision": "approve"},
        headers=hdr(token_factory, ["Approver"], "appr-1"),
    )
    growth = report(client, token_factory, "growth")
    assert growth["summary"]["created"] >= 1 and growth["rows"][-1][3] >= 1
    workflow = report(client, token_factory, "workflow")
    assert workflow["summary"]["reviews_opened"] >= 1 and workflow["summary"]["approved"] >= 1
    assert workflow["summary"]["average_hours_to_approval"] is not None


def test_storage_counts_each_stored_object_once(client, token_factory):
    upload(client, token_factory, title="Stored A")
    upload(client, token_factory, title="Stored B")
    storage = report(client, token_factory, "storage")
    assert storage["summary"]["stored_objects"] >= 2
    assert storage["summary"]["stored_bytes"] > 0
    assert sum(r[2] for r in storage["rows"]) == storage["summary"]["stored_bytes"]


def test_departments_and_reuse(client, token_factory):
    first = upload(client, token_factory, title="Reused A")
    upload(client, token_factory, title="Other")
    for name in ("Shelf one", "Shelf two"):
        created = client.post(
            "/api/v1/collections", json={"name": name}, headers=author(token_factory)
        )
        cid = created.json()["id"]
        client.put(
            f"/api/v1/collections/{cid}/items",
            json={"object_ids": [first]},
            headers=author(token_factory),
        )
    departments = report(client, token_factory, "departments")
    assert any(r[0] == "Unassigned" for r in departments["rows"])
    reuse = report(client, token_factory, "reuse")
    assert reuse["summary"]["reused_items"] >= 1
    assert reuse["summary"]["reuse_rate"] is not None


def test_drill_down_lists_the_items_behind_a_point(client, token_factory):
    lo_id = upload(client, token_factory, title="Drillable")
    drilled = client.get(
        "/api/v1/analytics/drill",
        params={"dimension": "status", "value": "draft"},
        headers=admin(token_factory),
    ).json()["items"]
    assert lo_id in {i["id"] for i in drilled}
    bad = client.get(
        "/api/v1/analytics/drill",
        params={"dimension": "password", "value": "x"},
        headers=admin(token_factory),
    )
    assert bad.status_code == 400


def test_filters_narrow_and_reject_bad_ranges(client, token_factory):
    upload(client, token_factory, title="Filter me")
    future = (datetime.now(UTC) + timedelta(days=5)).date().isoformat()
    empty = report(client, token_factory, "growth", start=future)
    assert empty["summary"]["created"] == 0
    bad = client.get(
        "/api/v1/analytics/reports/usage",
        params={"start": "2027-02-01", "end": "2027-01-01"},
        headers=admin(token_factory),
    )
    assert bad.status_code == 400


def test_csv_xlsx_and_pdf_exports_are_well_formed(client, token_factory):
    upload(client, token_factory, title="Exported")
    csv_response = client.get(
        "/api/v1/analytics/reports/storage/export",
        params={"format": "csv"},
        headers=admin(token_factory),
    )
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert csv_response.text.startswith("﻿# Storage")
    assert "Kind,Items,Stored bytes" in csv_response.text

    xlsx = client.get(
        "/api/v1/analytics/reports/storage/export",
        params={"format": "xlsx"},
        headers=admin(token_factory),
    ).content
    with zipfile.ZipFile(io.BytesIO(xlsx)) as archive:
        assert "xl/worksheets/sheet1.xml" in archive.namelist()
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        header = [
            c.findtext("m:is/m:t", namespaces=ns) for c in sheet.findall(".//m:row[@r='1']/m:c", ns)
        ]
    assert header == ["Kind", "Items", "Stored bytes"]

    pdf = client.get(
        "/api/v1/analytics/reports/storage/export",
        params={"format": "pdf"},
        headers=admin(token_factory),
    ).content
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    startxref = int(re.search(rb"startxref\n(\d+)", pdf).group(1))
    assert pdf[startxref : startxref + 4] == b"xref"
    count = int(re.search(rb"/Size (\d+)", pdf).group(1))
    offsets = [int(m.group(1)) for m in re.finditer(rb"(\d{10}) 00000 n", pdf)]
    assert len(offsets) == count - 1
    for number, offset in enumerate(offsets, start=1):
        assert pdf[offset : offset + len(f"{number} 0 obj")] == f"{number} 0 obj".encode()


def test_scheduled_report_runs_delivers_and_downloads(
    client, token_factory, db_session, monkeypatch
):
    upload(client, token_factory, title="Scheduled source")
    created = client.post(
        "/api/v1/analytics/schedules",
        headers=admin(token_factory),
        json={
            "name": "Weekly storage",
            "report": "storage",
            "format": "csv",
            "window_days": 30,
            "cadence": "weekly",
            "recipients": [],
        },
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    unknown = client.post(
        "/api/v1/analytics/schedules",
        headers=admin(token_factory),
        json={"name": "Bad", "report": "usage", "recipients": ["nobody-here"]},
    )
    assert unknown.status_code == 400

    run = client.post(f"/api/v1/analytics/schedules/{sid}/run", headers=admin(token_factory)).json()
    assert run["rows"] >= 1
    runs = client.get("/api/v1/analytics/runs", headers=admin(token_factory)).json()["items"]
    run_id = runs[0]["id"]
    downloaded = client.get(
        f"/api/v1/analytics/runs/{run_id}/download", headers=admin(token_factory)
    )
    assert downloaded.status_code == 200 and b"Kind,Items" in downloaded.content

    # Forcing the schedule due, then running the scheduler, produces a second run.
    row = db_session.get(ScheduledReport, sid)
    row.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    result = client.post("/api/v1/analytics/schedules/run-due", headers=admin(token_factory)).json()
    assert result == {"ran": 1, "failed": 0}
    assert (
        len(client.get("/api/v1/analytics/runs", headers=admin(token_factory)).json()["items"]) == 2
    )

    from app.db.models import Notification

    alerts = db_session.scalars(
        select(Notification).where(Notification.kind == "report_ready")
    ).all()
    assert alerts and alerts[0].recipient_subject == "root"


def test_schedules_belong_to_their_owner(client, token_factory):
    created = client.post(
        "/api/v1/analytics/schedules",
        headers=admin(token_factory),
        json={"name": "Mine", "report": "growth"},
    ).json()
    other = admin(token_factory, sub="someone-else")
    assert (
        client.put(
            f"/api/v1/analytics/schedules/{created['id']}", headers=other, json={"active": False}
        ).status_code
        == 404
    )
    assert client.get("/api/v1/analytics/schedules", headers=other).json()["items"] == []
    assert client.delete(
        f"/api/v1/analytics/schedules/{created['id']}", headers=admin(token_factory)
    ).json() == {"deleted": True}
