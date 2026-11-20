"""Workflow governance: multi-stage and parallel approvals, assignments, change requests,
resubmission, withdrawal, SLA escalation, separation of duties, notifications and email."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import EmailOutbox, Notification, ReviewCase, Role, StageTask, User, UserRole
from app.services import notifications as notify_service
from tests.conftest import build_package


def hdr(token_factory, roles, sub):
    return {"Authorization": f"Bearer {token_factory(roles, sub=sub)}"}


def upload(client, token_factory, title="Governed course"):
    response = client.post(
        "/api/v1/content",
        data={"title": title},
        files={"file": ("course.zip", build_package(), "application/zip")},
        headers=hdr(token_factory, ["Contributor"], "author-1"),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def policy(client, token_factory, name, stages):
    response = client.post(
        "/api/v1/workflow/policies",
        json={"name": name, "stages": stages},
        headers=hdr(token_factory, ["Repository Administrator"], "admin-1"),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def case(client, token_factory, lo_id, roles=("Repository Administrator",), sub="admin-1"):
    response = client.get(
        f"/api/v1/workflow/{lo_id}/case", headers=hdr(token_factory, list(roles), sub)
    )
    assert response.status_code == 200, response.text
    return response.json()


def decide(client, token_factory, lo_id, decision, roles, sub, comment=None):
    return client.post(
        f"/api/v1/workflow/{lo_id}/decision",
        json={"decision": decision, "comment": comment},
        headers=hdr(token_factory, roles, sub),
    )


TWO_STAGE = [
    {"name": "Review", "permission": "workflow.review", "approvals_required": 1},
    {"name": "Approval", "permission": "workflow.approve", "approvals_required": 1},
]


def test_multi_stage_policy_advances_stage_by_stage_then_approves(client, token_factory):
    pid = policy(client, token_factory, "Two stages", TWO_STAGE)
    lo_id = upload(client, token_factory)
    submitted = client.post(
        f"/api/v1/workflow/{lo_id}/submit",
        json={"policy_id": pid},
        headers=hdr(token_factory, ["Contributor"], "author-1"),
    )
    assert submitted.json()["status"] == "submitted"
    assert case(client, token_factory, lo_id)["stage_position"] == 1

    stage_one = decide(
        client, token_factory, lo_id, "approve", ["Reviewer"], "rev-1", "Content fine"
    )
    assert stage_one.status_code == 200, stage_one.text
    assert stage_one.json()["status"] == "submitted"  # moved on, not finished
    assert case(client, token_factory, lo_id)["stage_position"] == 2

    final = decide(client, token_factory, lo_id, "approve", ["Approver"], "appr-1", "Approved")
    assert final.json()["status"] == "approved"
    view = case(client, token_factory, lo_id)
    assert view["status"] == "approved" and view["policy"] == "Two stages"
    assert [t["state"] for t in view["tasks"]] == ["approved", "approved"]


def test_parallel_approvals_need_distinct_approvers(client, token_factory):
    pid = policy(
        client,
        token_factory,
        "Two of three",
        [
            {"name": "Panel", "permission": "workflow.approve", "approvals_required": 2},
        ],
    )
    lo_id = upload(client, token_factory)
    client.post(
        f"/api/v1/workflow/{lo_id}/submit",
        json={"policy_id": pid},
        headers=hdr(token_factory, ["Contributor"], "author-1"),
    )
    first = decide(client, token_factory, lo_id, "approve", ["Approver"], "panel-a", "ok")
    assert first.json()["status"] == "submitted"
    again = decide(client, token_factory, lo_id, "approve", ["Approver"], "panel-a", "ok twice")
    assert again.status_code == 400 and "already decided" in again.json()["message"]
    second = decide(client, token_factory, lo_id, "approve", ["Approver"], "panel-b", "ok")
    assert second.json()["status"] == "approved"


def test_named_assignees_only_decide_their_own_stage_until_reassigned(client, token_factory):
    pid = policy(
        client,
        token_factory,
        "Named",
        [
            {
                "name": "Alice only",
                "permission": "workflow.approve",
                "approvals_required": 1,
                "assignees": ["alice"],
            },
        ],
    )
    lo_id = upload(client, token_factory)
    client.post(
        f"/api/v1/workflow/{lo_id}/submit",
        json={"policy_id": pid},
        headers=hdr(token_factory, ["Contributor"], "author-1"),
    )
    intruder = decide(client, token_factory, lo_id, "approve", ["Approver"], "bob")
    assert intruder.status_code == 403 and "assigned to someone else" in intruder.json()["detail"]

    task_id = case(client, token_factory, lo_id)["tasks"][0]["id"]
    assigned = client.post(
        f"/api/v1/workflow/{lo_id}/tasks/{task_id}/assign",
        json={"assignee_subject": "bob"},
        headers=hdr(token_factory, ["Repository Administrator"], "admin-1"),
    )
    assert assigned.status_code == 200 and assigned.json()["assignee"] == "bob"
    assert (
        decide(client, token_factory, lo_id, "approve", ["Approver"], "bob").json()["status"]
        == "approved"
    )


def test_only_assignment_managers_can_reassign(client, token_factory):
    pid = policy(
        client,
        token_factory,
        "Assign guard",
        [{"name": "Pool", "permission": "workflow.approve", "approvals_required": 1}],
    )
    lo_id = upload(client, token_factory)
    client.post(
        f"/api/v1/workflow/{lo_id}/submit",
        json={"policy_id": pid},
        headers=hdr(token_factory, ["Contributor"], "author-1"),
    )
    task_id = case(client, token_factory, lo_id, ("Approver",), "appr-x")["tasks"][0]["id"]
    denied = client.post(
        f"/api/v1/workflow/{lo_id}/tasks/{task_id}/assign",
        json={"assignee_subject": "x"},
        headers=hdr(token_factory, ["Approver"], "appr-x"),
    )
    assert denied.status_code == 403


def test_change_request_then_resubmission_opens_a_new_round(client, token_factory):
    lo_id = upload(client, token_factory)
    client.post(
        f"/api/v1/workflow/{lo_id}/submit", headers=hdr(token_factory, ["Contributor"], "author-1")
    )
    no_comment = decide(client, token_factory, lo_id, "request_changes", ["Reviewer"], "rev-1")
    assert no_comment.status_code == 422

    asked = decide(
        client,
        token_factory,
        lo_id,
        "request_changes",
        ["Reviewer"],
        "rev-1",
        "Add alt text to the images",
    )
    assert asked.json()["status"] == "rejected"
    view = case(client, token_factory, lo_id)
    assert view["status"] == "changes_requested" and view["round"] == 1

    resubmitted = client.post(
        f"/api/v1/workflow/{lo_id}/resubmit",
        json={"comment": "Alt text added"},
        headers=hdr(token_factory, ["Contributor"], "author-1"),
    )
    assert resubmitted.status_code == 200 and resubmitted.json()["status"] == "submitted"
    new_round = case(client, token_factory, lo_id)
    assert new_round["round"] == 2 and new_round["status"] == "open"


def test_rejection_then_approval_and_separation_of_duties_on_publish(client, token_factory):
    lo_id = upload(client, token_factory)
    client.post(
        f"/api/v1/workflow/{lo_id}/submit", headers=hdr(token_factory, ["Contributor"], "author-1")
    )
    rejected = decide(client, token_factory, lo_id, "reject", ["Approver"], "appr-1", "Off topic")
    assert rejected.json()["status"] == "rejected"
    client.post(
        f"/api/v1/workflow/{lo_id}/resubmit",
        json={},
        headers=hdr(token_factory, ["Contributor"], "author-1"),
    )
    approved = decide(client, token_factory, lo_id, "approve", ["Approver"], "appr-1", "Now fine")
    assert approved.json()["status"] == "approved"

    same_person = client.post(
        f"/api/v1/workflow/{lo_id}/publish",
        headers=hdr(token_factory, ["Approver", "Publisher"], "appr-1"),
    )
    assert same_person.status_code == 403
    published = client.post(
        f"/api/v1/workflow/{lo_id}/publish", headers=hdr(token_factory, ["Publisher"], "pub-1")
    )
    assert published.json()["status"] == "published"


def test_withdraw_returns_item_to_draft(client, token_factory):
    lo_id = upload(client, token_factory)
    client.post(
        f"/api/v1/workflow/{lo_id}/submit", headers=hdr(token_factory, ["Contributor"], "author-1")
    )
    other = client.post(
        f"/api/v1/workflow/{lo_id}/withdraw", headers=hdr(token_factory, ["Contributor"], "someone")
    )
    assert other.status_code == 403
    done = client.post(
        f"/api/v1/workflow/{lo_id}/withdraw",
        headers=hdr(token_factory, ["Contributor"], "author-1"),
    )
    assert done.json()["status"] == "draft"
    assert case(client, token_factory, lo_id)["status"] == "withdrawn"


def test_sla_overdue_task_escalates_once_to_the_escalation_role(client, token_factory, db_session):
    db_session.add(Role(name="Repository Administrator"))
    db_session.flush()
    admin_role = db_session.scalar(select(Role).where(Role.name == "Repository Administrator"))
    db_session.add(User(subject="esc-admin", email="esc@example.test"))
    db_session.flush()
    esc_user = db_session.scalar(select(User).where(User.subject == "esc-admin"))
    db_session.add(UserRole(user_id=esc_user.id, role_id=admin_role.id))
    db_session.commit()

    pid = policy(
        client,
        token_factory,
        "Timed",
        [
            {
                "name": "Timed approval",
                "permission": "workflow.approve",
                "approvals_required": 1,
                "sla_hours": 24,
                "escalation_role": "Repository Administrator",
            }
        ],
    )
    lo_id = upload(client, token_factory)
    client.post(
        f"/api/v1/workflow/{lo_id}/submit",
        json={"policy_id": pid},
        headers=hdr(token_factory, ["Contributor"], "author-1"),
    )
    task = db_session.scalar(select(StageTask).where(StageTask.state == "open"))
    assert task.due_at is not None
    task.due_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()

    first = client.post(
        "/api/v1/workflow/sla/run", headers=hdr(token_factory, ["Super Administrator"], "root")
    )
    assert first.json() == {"escalated": 1}
    second = client.post(
        "/api/v1/workflow/sla/run", headers=hdr(token_factory, ["Super Administrator"], "root")
    )
    assert second.json() == {"escalated": 0}
    alerts = db_session.scalars(select(Notification).where(Notification.kind == "escalation")).all()
    assert {n.recipient_subject for n in alerts} == {"esc-admin"}


def test_queue_and_notifications_for_reviewers_and_submitters(client, token_factory):
    lo_id = upload(client, token_factory, title="Notify me")
    client.post(
        f"/api/v1/workflow/{lo_id}/submit", headers=hdr(token_factory, ["Contributor"], "author-1")
    )
    queue = client.get(
        "/api/v1/workflow/queue", headers=hdr(token_factory, ["Reviewer"], "rev-q")
    ).json()
    assert [q["title"] for q in queue["items"]] == []  # the default stage needs approve, not review
    approver_queue = client.get(
        "/api/v1/workflow/queue", headers=hdr(token_factory, ["Approver"], "appr-q")
    ).json()
    assert [q["title"] for q in approver_queue["items"]] == ["Notify me"]
    assert approver_queue["items"][0]["pooled"] is True

    decide(client, token_factory, lo_id, "approve", ["Approver"], "appr-q", "Go")
    feed = client.get(
        "/api/v1/notifications", headers=hdr(token_factory, ["Contributor"], "author-1")
    ).json()
    assert feed["unread"] >= 1 and any(n["kind"] == "approved" for n in feed["items"])
    first = feed["items"][0]["id"]
    read = client.post(
        f"/api/v1/notifications/{first}/read",
        headers=hdr(token_factory, ["Contributor"], "author-1"),
    )
    assert read.json()["read"] is True
    assert (
        client.post(
            f"/api/v1/notifications/{first}/read",
            headers=hdr(token_factory, ["Contributor"], "someone-else"),
        ).status_code
        == 404
    )
    client.post(
        "/api/v1/notifications/read-all", headers=hdr(token_factory, ["Contributor"], "author-1")
    )
    assert (
        client.get(
            "/api/v1/notifications?unread=true",
            headers=hdr(token_factory, ["Contributor"], "author-1"),
        ).json()["items"]
        == []
    )


def test_email_is_queued_then_dispatched_with_retry_on_failure(
    client, token_factory, db_session, monkeypatch
):
    user = db_session.scalar(select(User).where(User.subject == "author-1")) or User(
        subject="author-1"
    )
    user.email = "author@example.test"
    db_session.add(user)
    db_session.commit()
    lo_id = upload(client, token_factory, title="Emailed")
    client.post(
        f"/api/v1/workflow/{lo_id}/submit", headers=hdr(token_factory, ["Contributor"], "author-1")
    )
    decide(client, token_factory, lo_id, "approve", ["Approver"], "appr-e", "Ship it")
    queued = db_session.scalars(select(EmailOutbox)).all()
    assert any(
        row.recipient_email == "author@example.test" and row.status == "pending" for row in queued
    )

    admin = hdr(token_factory, ["Super Administrator"], "root")
    assert client.post("/api/v1/notifications/dispatch", headers=admin).json() == {
        "sent": 0,
        "failed": 0,
        "note": "SMTP is not configured",
    }

    class Down:
        def send(self, to, subject, body):
            raise OSError("smtp unreachable")

    assert notify_service.dispatch(db_session, Down())["failed"] >= 1
    db_session.expire_all()
    row = db_session.scalar(
        select(EmailOutbox).where(EmailOutbox.recipient_email == "author@example.test")
    )
    assert row.status == "pending" and row.attempts == 1 and "unreachable" in row.last_error

    sent_to = []

    class Up:
        def send(self, to, subject, body):
            sent_to.append(to)

    result = notify_service.dispatch(db_session, Up())
    assert result["sent"] >= 1 and "author@example.test" in sent_to


def test_policy_validation_and_permissions(client, token_factory):
    admin = hdr(token_factory, ["Repository Administrator"], "admin-1")
    bad_permission = client.post(
        "/api/v1/workflow/policies",
        headers=admin,
        json={"name": "Bad", "stages": [{"name": "x", "permission": "workflow.nonsense"}]},
    )
    assert bad_permission.status_code == 400
    too_many = client.post(
        "/api/v1/workflow/policies",
        headers=admin,
        json={
            "name": "Many",
            "stages": [
                {
                    "name": "x",
                    "permission": "workflow.approve",
                    "approvals_required": 3,
                    "assignees": ["a"],
                }
            ],
        },
    )
    assert too_many.status_code == 400
    assert (
        client.get(
            "/api/v1/workflow/policies", headers=hdr(token_factory, ["Reviewer"], "r")
        ).status_code
        == 403
    )
    pid = policy(
        client,
        token_factory,
        "Retire me",
        [{"name": "s", "permission": "workflow.approve", "approvals_required": 1}],
    )
    client.put(f"/api/v1/workflow/policies/{pid}", json={"active": False}, headers=admin)
    lo_id = upload(client, token_factory)
    inactive = client.post(
        f"/api/v1/workflow/{lo_id}/submit",
        json={"policy_id": pid},
        headers=hdr(token_factory, ["Contributor"], "author-1"),
    )
    assert inactive.status_code == 400 and "inactive" in inactive.json()["message"]


def test_policy_snapshot_protects_running_cases(client, token_factory, db_session):
    pid = policy(client, token_factory, "Snapshot", TWO_STAGE)
    lo_id = upload(client, token_factory)
    client.post(
        f"/api/v1/workflow/{lo_id}/submit",
        json={"policy_id": pid},
        headers=hdr(token_factory, ["Contributor"], "author-1"),
    )
    stored = db_session.scalar(select(ReviewCase).where(ReviewCase.lo_id == lo_id))
    assert len(stored.stages) == 2 and stored.stages[0]["name"] == "Review"


def test_resubmission_keeps_the_policy_of_the_previous_round(client, token_factory):
    pid = policy(client, token_factory, "Sticky path", TWO_STAGE)
    lo_id = upload(client, token_factory)
    client.post(f"/api/v1/workflow/{lo_id}/submit", json={"policy_id": pid},
                headers=hdr(token_factory, ["Contributor"], "author-1"))
    decide(client, token_factory, lo_id, "request_changes", ["Reviewer"], "rev-1", "Fix captions")
    client.post(f"/api/v1/workflow/{lo_id}/resubmit", json={},
                headers=hdr(token_factory, ["Contributor"], "author-1"))
    round_two = case(client, token_factory, lo_id)
    assert round_two["policy"] == "Sticky path" and len(round_two["stages"]) == 2
    # The first stage is still a review stage, so a reviewer can act on it.
    assert decide(client, token_factory, lo_id, "approve", ["Reviewer"], "rev-2").status_code == 200

