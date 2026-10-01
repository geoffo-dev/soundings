"""The worker's jobs (procrastinate; listed in :data:`app.worker.TASK_MODULES`).

| Task | Queue | When |
|---|---|---|
| ``send_email(email_id)`` | ``email`` | deferred with each outbox row, each retry and the sweep |
| ``sweep_outbox`` | ``email`` | every minute (also: jobs of crashed workers) |
| ``notify_event(event_id)`` | ``notifications`` | the fan-out of an event for many people |
| ``notification_schedule`` | ``notifications`` | hourly: reminders, digests, cleanup |
| ``remove_old_jobs`` | ``notifications`` | daily: failed/cancelled/aborted jobs after a week |

The periodic jobs have priority :data:`PERIODIC_PRIORITY` and ``notify_event``
:data:`FAN_OUT_PRIORITY` (``send_email`` 0): procrastinate runs higher priorities first,
so a backlog of sends (a slow or unreachable server) never delays the sweep, reminders,
digests or in-app notifications.

The jobs get the worker's :class:`~app.email.delivery.Runtime` (settings, sessions,
SMTP transport, clock) from the job context (``run_worker_async(additional_context=)``).
They never raise for SMTP errors: the outbox row records them and the next attempt is
its own job (procrastinate's own retry is unused).
"""

from __future__ import annotations

import logging
from typing import Final
from uuid import UUID

from procrastinate import App, JobContext
from procrastinate.exceptions import ConnectorException
from procrastinate.jobs import Status

from app.email import delivery
from app.email.delivery import Runtime
from app.notifications import fanout, schedule
from app.worker import procrastinate_app

__all__ = [
    "FAN_OUT_PRIORITY",
    "JOB_RETENTION_HOURS",
    "PERIODIC_PRIORITY",
    "RUNTIME_KEY",
    "STALLED_WORKER_SECONDS",
    "finish_stalled_jobs",
    "notification_schedule",
    "notify_event",
    "remove_old_jobs",
    "send_email",
    "sweep_outbox",
]

logger = logging.getLogger("soundings.worker")

RUNTIME_KEY: Final = "runtime"
JOB_RETENTION_HOURS: Final = 168
PERIODIC_PRIORITY: Final = 100
FAN_OUT_PRIORITY: Final = 50
STALLED_WORKER_SECONDS: Final = 120
"""A worker without a heartbeat this long is dead (it beats every 10 s)."""


def runtime_of(context: JobContext) -> Runtime:
    runtime = context.additional_context.get(RUNTIME_KEY)
    if not isinstance(runtime, Runtime):
        raise RuntimeError("run the jobs with `soundings worker` (no email runtime)")
    return runtime


@procrastinate_app.task(name="send_email", queue="email", pass_context=True)
async def send_email(context: JobContext, email_id: str) -> None:
    await delivery.send_email(runtime_of(context), UUID(email_id))


@procrastinate_app.task(
    name=fanout.NOTIFY_EVENT_TASK,
    queue="notifications",
    priority=FAN_OUT_PRIORITY,
    pass_context=True,
)
async def notify_event(context: JobContext, event_id: str) -> None:
    runtime = runtime_of(context)
    await fanout.notify_deferred_event(runtime.sessionmaker, runtime.settings, UUID(event_id))


@procrastinate_app.periodic(cron="* * * * *", periodic_id="sweep_outbox")
@procrastinate_app.task(
    name="sweep_outbox",
    queue="email",
    priority=PERIODIC_PRIORITY,
    pass_context=True,
    queueing_lock="sweep_outbox",
)
async def sweep_outbox(context: JobContext, timestamp: int) -> None:
    runtime = runtime_of(context)
    if runtime.jobs is not None:
        await finish_stalled_jobs(runtime.jobs)
    await delivery.sweep_outbox(runtime)


async def finish_stalled_jobs(app: App) -> int:
    """Mark the jobs a dead worker left ``doing`` (killed, out of memory) as failed, so
    the daily ``remove_old_jobs`` deletes them after a week. Nothing is re-run here:
    an outbox row in ``sending`` comes back through the sweep once its lease expires,
    and the periodic jobs run again on their schedule. Returns how many."""
    stalled = await app.job_manager.get_stalled_jobs(seconds_since_heartbeat=STALLED_WORKER_SECONDS)
    finished = 0
    for job in stalled:
        try:
            await app.job_manager.finish_job(job, status=Status.FAILED, delete_job=False)
        except ConnectorException:
            continue  # it finished meanwhile
        finished += 1
    if finished:
        logger.warning("jobs of a stopped worker marked failed", extra={"count": finished})
    return finished


@procrastinate_app.periodic(cron="0 * * * *", periodic_id="notification_schedule")
@procrastinate_app.task(
    name="notification_schedule",
    priority=PERIODIC_PRIORITY,
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
    priority=PERIODIC_PRIORITY,
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
