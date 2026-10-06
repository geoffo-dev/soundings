"""Talk to the fake agent with a2a-sdk **0.3.23**'s own client: the A2A library
kagent-adk 0.10.2 (the Python runtime in kagent's agent pods) is built on. Run in an
isolated environment, since the fake itself uses a2a-sdk 1.x:

    uv run --isolated --no-project --with a2a-sdk==0.3.23 \
        python compat/a2a_0_3_client.py http://127.0.0.1:8064/api/a2a/soundings/idea-evaluator/ \
        http://127.0.0.1:8064/api/a2a/soundings/idea-evaluator-slow/

Checks: the card resolves to a 0.3 JSON-RPC client, a streamed run reaches
``completed`` (task, status updates, artifact, final), ``tasks/get`` with
``historyLength`` 1, and ``tasks/cancel`` of a running task ends it ``canceled``.
Prints one line per check; exits 1 on the first failure.
"""

from __future__ import annotations

import asyncio
import sys
import uuid

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    Message,
    Part,
    Role,
    Task,
    TaskIdParams,
    TaskQueryParams,
    TaskState,
    TaskStatusUpdateEvent,
    TextPart,
)


def message(kind: str = "evaluate", idea: str = "CUST-12") -> Message:
    run_id = str(uuid.uuid4())
    return Message(
        message_id=run_id,
        role=Role.user,
        parts=[Part(root=TextPart(text=f"Soundings AI run {run_id} ({kind}) for idea {idea}."))],
        metadata={"soundings": {"run_id": run_id, "kind": kind, "idea": idea, "section_key": None}},
    )


async def check(url: str, slow_url: str) -> None:
    headers = {"X-User-Id": "soundings", "A2A-Version": "0.3"}
    async with httpx.AsyncClient(timeout=30, trust_env=False, headers=headers) as http:
        config = ClientConfig(streaming=True, httpx_client=http)
        client = await ClientFactory.connect(
            url, client_config=config, relative_card_path=".well-known/agent-card.json"
        )
        states: list[str] = []
        task: Task | None = None
        async for event in client.send_message(message()):
            if isinstance(event, Message):
                raise SystemExit("a direct message, not a task")
            task, update = event
            if isinstance(update, TaskStatusUpdateEvent):
                states.append(update.status.state.value)
        assert task is not None and task.status.state == TaskState.completed, states
        print(f"ok  0.3 stream: {' -> '.join(states)}")
        fetched = await client.get_task(TaskQueryParams(id=task.id, history_length=1))
        assert fetched.status.state == TaskState.completed
        assert len(fetched.history or []) <= 1
        print("ok  0.3 tasks/get (historyLength 1): completed")

        slow = await ClientFactory.connect(
            slow_url, client_config=config, relative_card_path=".well-known/agent-card.json"
        )
        stream = slow.send_message(message())
        first = await anext(stream)
        assert not isinstance(first, Message)
        task_id = first[0].id
        await anext(stream)  # working
        cancelled = await slow.cancel_task(TaskIdParams(id=task_id))
        assert cancelled.status.state == TaskState.canceled, cancelled.status.state
        print("ok  0.3 tasks/cancel: canceled")


if __name__ == "__main__":
    asyncio.run(check(sys.argv[1], sys.argv[2]))
