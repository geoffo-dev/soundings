"""The worker's jobs (procrastinate; listed in :data:`app.worker.TASK_MODULES`).

| Task | Queue | When |
|---|---|---|
| ``send_email(email_id)`` | ``email`` | deferred with each outbox row, each retry and the sweep |
| ``sweep_outbox`` | ``email`` | every minute |
| ``notification_schedule`` | ``notifications`` | hourly: reminders, digests, cleanup |
| ``remove_old_jobs`` | ``notifications`` | daily: failed/cancelled/aborted jobs after a week |

The jobs get the worker's :class:`~app.email.delivery.Runtime` (settings, sessions,
SMTP transport, clock) from the job context (``run_worker_async(additional_context=)``).
They never raise for SMTP errors: the outbox row records them and the next attempt is
its own job (procrastinate's own retry is unused).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from procrastinate import JobContext

from app.email import delivery
from app.email.delivery import Runtime
from app.notifications import schedule
from app.worker import procrastinate_app

__all__ = [
    "JOB_RETENTION_HOURS",
    "RUNTIME_KEY",
    "notification_schedule",
    "remove_old_jobs",
    "send_email",
    "sweep_outbox",
]

RUNTIME_KEY: Final = "runtime"
JOB_RETENTION_HOURS: Final = 168


def runtime_of(context: JobContext) -> Runtime:
    runtime = context.additional_context.get(RUNTIME_KEY)
    if not isinstance(runtime, Runtime):
        raise RuntimeError("run the jobs with `soundings worker` (no email runtime)")
    return runtime


@procrastinate_app.task(name="send_email", queue="email", pass_context=True)
async def send_email(context: JobContext, email_id: str) -> None:
    await delivery.send_email(runtime_of(context), UUID(email_id))


@procrastinate_app.periodic(cron="* * * * *", periodic_id="sweep_outbox")
@procrastinate_app.task(
    name="sweep_outbox", queue="email", pass_context=True, queueing_lock="sweep_outbox"
)
async def sweep_outbox(context: JobContext, timestamp: int) -> None:
    await delivery.sweep_outbox(runtime_of(context))


@procrastinate_app.periodic(cron="0 * * * *", periodic_id="notification_schedule")
@procrastinate_app.task(
    name="notification_schedule",
    queue="notifications",
    pass_context=True,
    queueing_lock="notification_schedule",
)
async def notification_schedule(context: JobContext, timestamp: int) -> None:
    runtime = runtime_of(context)
    await schedule.run_schedule(runtime.sessionmaker, runtime.settings, runtime.clock())


@procrastinate_app.periodic(cron="17 3 * * *", periodic_id="remove_old_jobs")
@procrastinate_app.task(
    name="remove_old_jobs",
    queue="notifications",
    pass_context=True,
    queueing_lock="remove_old_jobs",
)
async def remove_old_jobs(context: JobContext, timestamp: int) -> None:
    """procrastinate's builtin ``remove_old_jobs`` (a periodic task must take the
    ``timestamp``, which the builtin doesn't): finished jobs older than a week,
    including failed, cancelled and aborted ones."""
    assert context.app is not None  # noqa: S101 - set by the worker
    await context.app.job_manager.delete_old_jobs(
        nb_hours=JOB_RETENTION_HOURS,
        include_failed=True,
        include_cancelled=True,
        include_aborted=True,
    )
