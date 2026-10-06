"""The AI jobs (procrastinate; listed in :data:`app.worker.TASK_MODULES`).

| Task | Queue | When |
|---|---|---|
| ``run_ai(run_id)`` | ``ai`` (its own pool) | with each new run, on the request's connection |
| ``sweep_ai_runs`` | ``notifications`` (main pool) | every minute: stale and long-queued runs |

``run_ai`` runs on the worker's ``ai`` pool (``SOUNDINGS_AI_MAX_CONCURRENT_RUNS`` at once),
so runs that hold a slot for minutes never delay email, notifications or the schedules;
the sweep runs on the main pool, so a full ``ai`` pool can't delay it either. Neither is
ever retried by procrastinate: the run row is the state (contract-phase6 section 3.3).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from procrastinate import JobContext

from app.ai.runner import AiRuntime, execute_run, sweep_runs
from app.ai.runs import RUN_AI_TASK
from app.email.tasks import PERIODIC_PRIORITY
from app.schemas.ai import AI_RUN_QUEUE
from app.worker import procrastinate_app

__all__ = ["AI_RUNTIME_KEY", "ai_runtime_of", "run_ai", "sweep_ai_runs"]

AI_RUNTIME_KEY: Final = "ai_runtime"


def ai_runtime_of(context: JobContext) -> AiRuntime:
    runtime = context.additional_context.get(AI_RUNTIME_KEY)
    if not isinstance(runtime, AiRuntime):
        raise RuntimeError("run the jobs with `soundings worker` (no AI runtime)")
    return runtime


@procrastinate_app.task(name=RUN_AI_TASK, queue=AI_RUN_QUEUE, pass_context=True)
async def run_ai(context: JobContext, run_id: str) -> None:
    await execute_run(ai_runtime_of(context), UUID(run_id))


@procrastinate_app.periodic(cron="* * * * *", periodic_id="sweep_ai_runs")
@procrastinate_app.task(
    name="sweep_ai_runs",
    queue="notifications",
    priority=PERIODIC_PRIORITY,
    pass_context=True,
    queueing_lock="sweep_ai_runs",
)
async def sweep_ai_runs(context: JobContext, timestamp: int) -> None:
    await sweep_runs(ai_runtime_of(context))
