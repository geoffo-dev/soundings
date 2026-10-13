"""The bid jobs (procrastinate; listed in :data:`app.worker.TASK_MODULES`).

* ``extract_bid_document(document_id)``, queue ``bid_documents`` (a pool of its own, one
  at a time): with each upload, on the request's connection; again after a crash.
* ``check_bid_ai_assessor(call_id)``, queue ``notifications``: when a call's AI assessor
  is set or the call opens or closes to new bids: its automatic runs that are due.
* ``sweep_bid_documents``, queue ``notifications``, every minute: lost extraction jobs,
  and every automatic run that is due (the quiet period after uploads ended).

Neither is retried by procrastinate: the document row is the state (its attempts and
extraction state), as the outbox row is for email.
"""

from __future__ import annotations

from uuid import UUID

from procrastinate import JobContext

from app.bids import assess, extraction
from app.email.tasks import PERIODIC_PRIORITY, runtime_of
from app.worker import procrastinate_app

__all__ = ["check_bid_ai_assessor", "extract_bid_document", "sweep_bid_documents"]


@procrastinate_app.task(
    name=extraction.EXTRACT_TASK, queue=extraction.BID_DOCUMENT_QUEUE, pass_context=True
)
async def extract_bid_document(context: JobContext, document_id: str) -> None:
    runtime = runtime_of(context)

    async def on_done(bid_id: UUID) -> None:
        await assess.check_after_extraction(
            runtime.sessionmaker, runtime.settings, bid_id, now=runtime.clock()
        )

    await extraction.extract_document(runtime.sessionmaker, UUID(document_id), on_done=on_done)


@procrastinate_app.task(name=assess.AUTO_CHECK_TASK, queue="notifications", pass_context=True)
async def check_bid_ai_assessor(context: JobContext, call_id: str) -> None:
    runtime = runtime_of(context)
    await assess.start_due_automatic_runs(
        runtime.sessionmaker, runtime.settings, call_id=UUID(call_id), now=runtime.clock()
    )


@procrastinate_app.periodic(cron="* * * * *", periodic_id="sweep_bid_documents")
@procrastinate_app.task(
    name="sweep_bid_documents",
    queue="notifications",
    priority=PERIODIC_PRIORITY,
    pass_context=True,
    queueing_lock="sweep_bid_documents",
)
async def sweep_bid_documents(context: JobContext, timestamp: int) -> None:
    runtime = runtime_of(context)
    await extraction.sweep_documents(runtime.sessionmaker)
    await assess.start_due_automatic_runs(
        runtime.sessionmaker, runtime.settings, now=runtime.clock()
    )
