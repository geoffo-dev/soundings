"""The worker: procrastinate runs the jobs with the email runtime, deletes finished
jobs (bounded job table), and the periodic jobs are registered (contract-phase3
section 3.9)."""

from __future__ import annotations

import pytest
from procrastinate import App
from procrastinate.jobs import Status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.email import tasks
from app.email.delivery import Runtime
from app.models.enums import EmailStatus
from app.worker import TASK_MODULES, procrastinate_app, worker_options
from tests.notifications.conftest import AsUser, Outbox, RecordingTransport, Team, ok, only

pytestmark = pytest.mark.usefixtures("team")


def test_the_jobs_are_registered() -> None:
    assert TASK_MODULES == ["app.email.tasks", "app.ai.tasks"]
    procrastinate_app.perform_import_paths()  # type: ignore[no-untyped-call]
    assert {
        "send_email",
        "sweep_outbox",
        "notification_schedule",
        "remove_old_jobs",
        "run_ai",
        "sweep_ai_runs",
    } <= set(procrastinate_app.tasks)
    periodic = {
        task.task.name: task.cron
        for task in procrastinate_app.periodic_registry.periodic_tasks.values()
    }
    assert periodic == {
        "sweep_outbox": "* * * * *",
        "notification_schedule": "0 * * * *",
        "remove_old_jobs": "17 3 * * *",
        "sweep_ai_runs": "* * * * *",
    }
    assert procrastinate_app.tasks["send_email"].queue == "email"
    assert procrastinate_app.tasks["notification_schedule"].queue == "notifications"
    # Phase 6: runs on the ai queue (the worker's own pool); the sweep on the main pool.
    assert procrastinate_app.tasks["run_ai"].queue == "ai"
    assert procrastinate_app.tasks["sweep_ai_runs"].queue == "notifications"


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


async def test_jobs_of_a_crashed_worker_are_finished_as_failed(
    jobs: App, db_session: AsyncSession
) -> None:
    """Review L7: after a SIGKILL the worker's jobs stayed ``doing`` forever (the daily
    cleanup only removes finished jobs). Their outbox rows recover through the sweep."""
    for n in range(3):
        await jobs.configure_task("send_email").defer_async(email_id=f"{n:032x}")
    dead = await jobs.job_manager.register_worker()
    alive = await jobs.job_manager.register_worker()
    crashed = [await jobs.job_manager.fetch_job(None, dead) for _ in range(2)]
    running = await jobs.job_manager.fetch_job(None, alive)
    assert running is not None
    assert all(job is not None for job in crashed)
    await db_session.execute(
        text(
            "UPDATE procrastinate_workers SET last_heartbeat = now() - interval '10 minutes'"
            " WHERE id = :id"
        ),
        {"id": dead},
    )
    # Another worker started meanwhile and pruned a third crashed worker: no worker id.
    await db_session.execute(
        text("UPDATE procrastinate_jobs SET worker_id = NULL WHERE id = :id"),
        {"id": crashed[1].id if crashed[1] else None},
    )
    await db_session.commit()

    assert await tasks.finish_stalled_jobs(jobs) == 2

    rows = await db_session.execute(text("SELECT id, status FROM procrastinate_jobs ORDER BY id"))
    statuses = {row.id: row.status for row in rows}
    await db_session.commit()
    assert [statuses[job.id] for job in crashed if job] == ["failed", "failed"]
    assert statuses[running.id] == "doing"
    assert await tasks.finish_stalled_jobs(jobs) == 0
    await jobs.job_manager.finish_job(running, status=Status.SUCCEEDED, delete_job=True)
    await jobs.job_manager.unregister_worker(alive)
    await jobs.job_manager.unregister_worker(dead)
