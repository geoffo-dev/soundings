"""The worker: procrastinate runs the jobs with the email runtime, deletes finished
jobs (bounded job table), and the periodic jobs are registered (contract-phase3
section 3.9)."""

from __future__ import annotations

import pytest
from procrastinate import App

from app.email import tasks
from app.email.delivery import Runtime
from app.models.enums import EmailStatus
from app.worker import TASK_MODULES, procrastinate_app, worker_options
from tests.notifications.conftest import AsUser, Outbox, RecordingTransport, Team, ok, only

pytestmark = pytest.mark.usefixtures("team")


def test_the_jobs_are_registered() -> None:
    assert TASK_MODULES == ["app.email.tasks"]
    procrastinate_app.perform_import_paths()  # type: ignore[no-untyped-call]
    assert {"send_email", "sweep_outbox", "notification_schedule", "remove_old_jobs"} <= set(
        procrastinate_app.tasks
    )
    periodic = {
        task.task.name: task.cron
        for task in procrastinate_app.periodic_registry.periodic_tasks.values()
    }
    assert periodic == {
        "sweep_outbox": "* * * * *",
        "notification_schedule": "0 * * * *",
        "remove_old_jobs": "17 3 * * *",
    }
    assert procrastinate_app.tasks["send_email"].queue == "email"
    assert procrastinate_app.tasks["notification_schedule"].queue == "notifications"


async def test_the_worker_sends_queued_mail_and_keeps_no_finished_jobs(
    api: AsUser,
    team: Team,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    jobs: App,
) -> None:
    idea = await (await api(team.member)).create_idea(team.slug)
    body = {"user_id": str(team.owner.id)}
    ok(await (await api(team.admin)).put(f"/ideas/{idea['key']}/owner", body))
    email = only(await outbox.emails())

    options = worker_options(concurrency=1, runtime=runtime)
    await jobs.run_worker_async(**options, queues=["email"], wait=False)

    assert (await outbox.email(email.id)).status is EmailStatus.SENT
    assert len(transport.sent) == 1
    assert await outbox.jobs() == []  # delete_jobs="successful"


def test_the_jobs_need_the_worker_runtime() -> None:
    class Context:
        additional_context: dict[str, object] = {}  # noqa: RUF012

    with pytest.raises(RuntimeError, match="soundings worker"):
        tasks.runtime_of(Context())  # type: ignore[arg-type]
