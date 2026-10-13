"""The agents' behaviour: one ``AgentExecutor`` per served agent (namespace/name).

A run arrives as one A2A message whose ``metadata.soundings`` says what to do
(``run_id``, ``kind``, ``idea``, ``section_key``; Phase 10's ``assess_bid`` runs also
``bid_id``); the text is for a model and is only
checked for what must never be in it. The work is done through Soundings' MCP tools
with the agent's own key, exactly as a kagent agent would call them (every call naming
the run's id as ``run_id``), so Soundings' rules (c22 run scope, blind evaluation, result
matching) are exercised for real; only the model is missing. Everything is deterministic.
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from a2a.helpers.proto_helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types.a2a_pb2 import Message, Part, TaskState
from google.protobuf import json_format

from fake_agent.config import Settings
from fake_agent.mcp import McpClient, McpTransportError, ToolResult
from fake_agent.observations import Observations, message_checks

log = logging.getLogger("fake_agent")

SECTION_KEY = re.compile(r"[a-z][a-z0-9_]{0,39}")
"""A proposal section's key as Soundings writes it (each project has its own template:
``summary``, ``risks``, ``carbon_impact``…). The fake checks only its shape; whether the
section exists is read from ``get_proposal``, as a real agent would."""
KINDS = ("evaluate", "research", "draft_section", "assess_bid")
WRITE_TOOLS = {
    "evaluate": "submit_evaluation",
    "research": "add_research_note",
    "draft_section": "propose_proposal_section",
    "assess_bid": "submit_bid_assessment",
}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
IDEA_KEY = re.compile(r"([A-Z][A-Z0-9]{0,9})-([1-9][0-9]{0,8})")
SOURCE_BASE = "https://example.org/fake-agent"
"""Every source the fake cites starts with this, so tests can search for it (it must
never reach a pending evaluator, a progress event or an error message)."""
RATIONALE_MARKER = "fake-rationale"
"""Every rationale the fake writes starts with this (the same purpose)."""
INVENTED_QUOTE = (
    "We guarantee delivery in three days at no cost (fake-invented-quote: in no document)."
)
"""``-invents``: the quote the fake gives as evidence although no document holds it, so
Soundings must mark it "not found in the document" (contract-phase10 section 9.3)."""
QUOTE_MIN, QUOTE_MAX = 20, 300
"""The passages the fake quotes: Soundings takes 20-500 characters once whitespace is
normalised; the fake stays well inside."""
MAX_PAGES = 10
"""Pages of one document the fake reads at most (20,000 characters each)."""
PLACEHOLDER_ID = "00000000-0000-0000-0000-000000000000"


class _Stop(Exception):  # noqa: N818 (a signal, not an error)
    """End the task in ``state`` (raised from inside the work); ``name`` for logs."""

    def __init__(self, state: TaskState, name: str, text: str) -> None:
        super().__init__(text)
        self.state = state
        self.name = name
        self.text = text


@dataclass(frozen=True)
class Run:
    run_id: str
    kind: str
    idea: str
    section_key: str | None
    bid_id: str | None = None
    """``assess_bid`` runs only: the bid the run names (its calls reach only that bid)."""


def _metadata_of(message: Message | None) -> dict[str, Any]:
    if message is None or not message.HasField("metadata"):
        return {}
    return json_format.MessageToDict(message.metadata)


def _run_from(context: RequestContext) -> Run | None:
    soundings = _metadata_of(context.message).get("soundings")
    if not isinstance(soundings, dict):
        return None
    run_id, kind, idea = soundings.get("run_id"), soundings.get("kind"), soundings.get("idea")
    section = soundings.get("section_key")
    if not (isinstance(run_id, str) and kind in KINDS and isinstance(idea, str)):
        return None
    if not IDEA_KEY.fullmatch(idea) or not re.fullmatch(r"[0-9a-f-]{36}", run_id):
        return None
    if kind == "draft_section":
        if not (isinstance(section, str) and SECTION_KEY.fullmatch(section)):
            return None
    else:
        section = None
    bid_id = soundings.get("bid_id")
    if kind == "assess_bid":
        if not (isinstance(bid_id, str) and UUID.fullmatch(bid_id)):
            return None
    else:
        bid_id = None
    return Run(run_id=run_id, kind=kind, idea=idea, section_key=section, bid_id=bid_id)


def with_run(run: Run, arguments: dict[str, Any]) -> dict[str, Any]:
    """Every Soundings tool call names its run (``run_id``, from the run's message), as
    the message tells a model to: Soundings binds the call to that run (c22)."""
    return {"run_id": run.run_id, **arguments}


def first_read(run: Run) -> tuple[str, dict[str, Any]]:
    """The read a run starts with: the bid for an assess run (which may read nothing
    else), the idea for the others."""
    if run.kind == "assess_bid":
        return "get_bid_for_assessment", {"bid_id": run.bid_id}
    return "get_idea", {"idea": run.idea}


def _text_of(message: Message | None) -> str:
    if message is None:
        return ""
    return "\n".join(part.text for part in message.parts if part.HasField("text"))


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class FakeAgentExecutor(AgentExecutor):
    def __init__(
        self,
        *,
        namespace: str,
        name: str,
        settings: Settings,
        observations: Observations,
    ) -> None:
        self.namespace = namespace
        self.name = name
        self.settings = settings
        self.observations = observations
        self._cancelled: dict[str, asyncio.Event] = {}
        self._late_tasks: set[asyncio.Task[None]] = set()

    @property
    def behaviour(self) -> str:
        return self.settings.behaviour_for(self.namespace, self.name)

    # --- A2A ----------------------------------------------------------------------------
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        task = context.current_task
        if task is None:
            if message is None:
                return
            task = new_task_from_user_message(message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        run = _run_from(context)
        if run is None:
            # Not a Soundings run (someone typing in kagent's UI): answer, do nothing.
            await updater.complete(self._say(updater, "I only handle Soundings runs."))
            return
        behaviour = self.behaviour
        self.observations.link_task(run.run_id, task.id, task.context_id)
        self.observations.start(
            run.run_id,
            agent=f"{self.namespace}/{self.name}",
            behaviour=behaviour,
            kind=run.kind,
            idea=run.idea,
            section_key=run.section_key,
            message_id=message.message_id if message else None,
            message_context_id=message.context_id if message else None,
            message_checks=message_checks(_text_of(message), _metadata_of(message)),
        )
        log.info("run %s (%s, %s): started", run.run_id, run.kind, behaviour)
        cancelled = self._cancelled.setdefault(task.id, asyncio.Event())
        state = "completed"
        try:
            if behaviour == "rejects":
                await updater.reject(self._say(updater, "I decline this request."))
                state = "rejected"
                return
            await updater.start_work(self._say(updater, "Working on it."))
            if behaviour == "late":
                late = asyncio.create_task(self._late_write(run, cancelled))
                self._late_tasks.add(late)
                late.add_done_callback(self._late_tasks.discard)
            try:
                text = await self._work(run, behaviour, updater, cancelled)
            except _Stop as stop:
                await updater.update_status(stop.state, self._say(updater, stop.text))
                state = stop.name
                return
            except McpTransportError as error:
                log.info("run %s: MCP unreachable (%s)", run.run_id, error)
                await updater.failed(self._say(updater, "I couldn't reach Soundings."))
                state = "failed"
                return
            await updater.add_artifact([Part(text=text)], name="result")
            await updater.complete(self._say(updater, text))
        except asyncio.CancelledError:
            state = "canceled"
            raise
        finally:
            self._cancelled.pop(task.id, None)
            self.observations.finish(run.run_id, state)
            log.info("run %s: %s", run.run_id, state)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id or ""
        run_id = self.observations.run_for_task(task_id)
        event = self._cancelled.get(task_id)
        if event is not None:
            event.set()
        if self.behaviour == "no-cancel":
            # kagent-adk 0.10.2 (the Python runtime) raises this; A2A answers -32603.
            raise NotImplementedError("cancel is not supported")
        task = context.current_task
        updater = TaskUpdater(event_queue, task_id, task.context_id if task else "")
        with suppress(RuntimeError):  # already terminal
            await updater.cancel(self._say(updater, "Cancelled."))
        if run_id:
            self.observations.finish(run_id, "canceled")

    @staticmethod
    def _say(updater: TaskUpdater, text: str) -> Message:
        return updater.new_agent_message([Part(text=text)])

    # --- The work -----------------------------------------------------------------------
    def _client(self) -> McpClient:
        key = self.settings.key_for(self.namespace, self.name)
        if key is None or not self.settings.mcp_url:
            raise McpTransportError("no key or MCP URL configured for this agent")
        return McpClient(self.settings.mcp_url, key, timeout=self.settings.mcp_timeout)

    async def _call(
        self, mcp: McpClient, run: Run, tool: str, arguments: dict[str, Any], phase: str = "work"
    ) -> ToolResult:
        result = await mcp.call(tool, with_run(run, arguments))
        self.observations.tool_call(run.run_id, tool, result.error_code, phase)
        return result

    async def _step(self, updater: TaskUpdater, text: str) -> None:
        await asyncio.sleep(self.settings.step_delay)
        await updater.update_status(TaskState.TASK_STATE_WORKING, self._say(updater, text))

    async def _work(
        self, run: Run, behaviour: str, updater: TaskUpdater, cancelled: asyncio.Event
    ) -> str:
        if behaviour == "silent":
            await self._step(updater, "Thinking.")
            return "Done (without saving anything)."
        async with self._client() as mcp:
            if behaviour == "asks":
                await self._call(mcp, run, *first_read(run))
                raise _Stop(
                    TaskState.TASK_STATE_INPUT_REQUIRED,
                    "input_required",
                    "Which market do you mean?",
                )
            if behaviour == "fails":
                await self._call(mcp, run, *first_read(run))
                raise _Stop(TaskState.TASK_STATE_FAILED, "failed", "Something went wrong.")
            if behaviour in ("slow", "late", "no-cancel"):
                await self._call(mcp, run, *first_read(run))
                await self._keep_working(updater, cancelled)
            if behaviour == "drops":
                # The stream is cut after two events (app.py); work on meanwhile, so the
                # client has to poll tasks/get for the outcome.
                await asyncio.sleep(max(3.0, self.settings.step_delay))
            if behaviour == "blind-probe":
                await self._probe(mcp, run, "before")
            if behaviour == "strays":
                await self._stray(mcp, run)
            text = await self._do(mcp, run, updater, behaviour)
            if behaviour == "blind-probe":
                await self._probe(mcp, run, "after")
            if behaviour == "lingers":
                await self._keep_working(updater, cancelled)
            return text

    async def _keep_working(self, updater: TaskUpdater, cancelled: asyncio.Event) -> None:
        """Status updates every ``slow_interval`` until cancelled (or the run's deadline,
        when the worker cancels): the framework cancels this coroutine on tasks/cancel."""
        while not cancelled.is_set():
            await updater.update_status(
                TaskState.TASK_STATE_WORKING, self._say(updater, "Still working.")
            )
            with suppress(TimeoutError):
                await asyncio.wait_for(cancelled.wait(), self.settings.slow_interval)
        raise asyncio.CancelledError

    async def _do(self, mcp: McpClient, run: Run, updater: TaskUpdater, behaviour: str) -> str:
        if run.kind == "evaluate":
            return await self._evaluate(mcp, run, updater)
        if run.kind == "research":
            return await self._research(mcp, run, updater)
        if run.kind == "assess_bid":
            return await self._assess(mcp, run, updater, behaviour)
        return await self._draft(mcp, run, updater)

    async def _evaluate(self, mcp: McpClient, run: Run, updater: TaskUpdater) -> str:
        rubric = await self._call(mcp, run, "get_rubric", {"idea": run.idea})
        if rubric.is_error:
            return f"I couldn't read the rubric ({rubric.error_code})."
        await self._step(updater, "Read the rubric.")
        idea = await self._call(mcp, run, "get_idea", {"idea": run.idea})
        if idea.is_error:
            return f"I couldn't read the idea ({idea.error_code})."
        await self._step(updater, "Read the idea.")
        arguments = evaluation_arguments(run.idea, rubric.content.get("criteria") or [])
        saved = await self._call(mcp, run, "submit_evaluation", arguments)
        if saved.is_error:
            return f"I couldn't save my evaluation ({saved.error_code})."
        return f"Submitted my evaluation of {run.idea}."

    async def _research(self, mcp: McpClient, run: Run, updater: TaskUpdater) -> str:
        idea = await self._call(mcp, run, "get_idea", {"idea": run.idea})
        if idea.is_error:
            return f"I couldn't read the idea ({idea.error_code})."
        await self._step(updater, "Read the idea; researching.")
        saved = await self._call(mcp, run, "add_research_note", research_arguments(run.idea))
        if saved.is_error:
            return f"I couldn't save the note ({saved.error_code})."
        return f"Wrote a research note on {run.idea}."

    async def _draft(self, mcp: McpClient, run: Run, updater: TaskUpdater) -> str:
        idea = await self._call(mcp, run, "get_idea", {"idea": run.idea})
        if idea.is_error:
            return f"I couldn't read the idea ({idea.error_code})."
        proposal = await self._call(mcp, run, "get_proposal", {"idea": run.idea})
        if proposal.is_error or not proposal.content.get("proposal"):
            return f"There is no proposal to draft for ({proposal.error_code or 'none'})."
        await self._step(updater, "Read the proposal.")
        sections = proposal.content["proposal"].get("sections") or []
        section = next((s for s in sections if s.get("key") == run.section_key), None)
        if section is None:
            return "That section isn't in the proposal."
        arguments = draft_arguments(run.idea, section)
        saved = await self._call(mcp, run, "propose_proposal_section", arguments)
        if saved.is_error:
            return f"I couldn't save the suggestion ({saved.error_code})."
        return f"Suggested text for the {section.get('title') or run.section_key} section."

    async def _assess(self, mcp: McpClient, run: Run, updater: TaskUpdater, behaviour: str) -> str:
        """Phase 10: read the bid and every document's text it may read (never pricing
        documents: Soundings doesn't list them), then one assessment with quotes taken
        from that text (``-invents``: one quote that is in no document; ``-not-met``: the
        first must-have found not met)."""
        bid = await self._call(mcp, run, "get_bid_for_assessment", {"bid_id": run.bid_id})
        if bid.is_error:
            return f"I couldn't read the bid ({bid.error_code})."
        await self._step(updater, "Read the bid.")
        documents = [d for d in bid.content.get("documents") or [] if isinstance(d, dict)]
        texts: dict[str, str] = {}
        pages_read = 0
        for document in documents:
            if document.get("extraction_state") != "done":
                continue
            pages = min(int(document.get("page_count") or 0), MAX_PAGES)
            parts = []
            for page in range(1, pages + 1):
                text = await self._call(
                    mcp,
                    run,
                    "get_bid_document_text",
                    {"bid_id": run.bid_id, "document_id": document["id"], "page": page},
                )
                if text.is_error:
                    break
                pages_read += 1
                parts.append(str(text.content.get("text") or ""))
            texts[str(document["id"])] = "".join(parts)
        await self._step(updater, f"Read {len(texts)} of {len(documents)} documents.")
        call = bid.content.get("call") or {}
        arguments = assessment_arguments(
            str(run.bid_id),
            call,
            [str(d["id"]) for d in documents],
            texts,
            invent=behaviour == "invents",
            not_met=behaviour == "not-met",
        )
        saved = await self._call(mcp, run, "submit_bid_assessment", arguments)
        self.observations.assess(
            run.run_id,
            {
                "bid_id": run.bid_id,
                "documents_listed": [str(d["id"]) for d in documents],
                "documents_read": sorted(texts),
                "pages_read": pages_read,
                "questions": len(arguments["scores"]),
                "must_haves": len(arguments["findings"]),
                "quotes": sum(len(s["evidence"]) for s in arguments["scores"])
                + sum(len(f["evidence"]) for f in arguments["findings"]),
                "invented": behaviour == "invents",
                "findings": {f["must_have_id"]: f["finding"] for f in arguments["findings"]},
                "error_code": saved.error_code,
                "quotes_checked": saved.content.get("quotes_checked"),
                "quotes_not_found": saved.content.get("quotes_not_found"),
            },
        )
        if saved.is_error:
            return f"I couldn't save my assessment ({saved.error_code})."
        return f"Submitted my assessment of bid {run.bid_id}."

    # --- Test behaviours ----------------------------------------------------------------
    async def _probe(self, mcp: McpClient, run: Run, phase: str) -> None:
        """Rule 9: what an agent sees of others' score data, before and after its work."""
        if run.kind == "assess_bid":
            await self._probe_bid(mcp, run, phase)
            return
        idea = await self._call(mcp, run, "get_idea", {"idea": run.idea}, phase=f"probe-{phase}")
        if not idea.is_error:
            detail = idea.content.get("idea") or {}
            mine = detail.get("my_evaluation") or {}
            self.observations.blind(
                run.run_id,
                {
                    "tool": "get_idea",
                    "phase": phase,
                    "score_hidden": detail.get("score_hidden"),
                    "score": detail.get("score"),
                    "aggregate": detail.get("aggregate"),
                    "evaluation_count": detail.get("evaluation_count"),
                    "evaluations": len(detail.get("evaluations") or []),
                    "high_disagreement": detail.get("high_disagreement"),
                    "my_evaluation_state": mine.get("state"),
                },
            )
        found = await self._call(
            mcp, run, "search_ideas", {"query": run.idea, "limit": 50}, phase=f"probe-{phase}"
        )
        if not found.is_error:
            items = found.content.get("items") or []
            item = next((i for i in items if i.get("key") == run.idea), None)
            self.observations.blind(
                run.run_id,
                {
                    "tool": "search_ideas",
                    "phase": phase,
                    "found": item is not None,
                    "keys": [i.get("key") for i in items][:20],
                    "score_hidden": item.get("score_hidden") if item else None,
                    "score": item.get("score") if item else None,
                    "high_disagreement": item.get("high_disagreement") if item else None,
                },
            )

    async def _probe_bid(self, mcp: McpClient, run: Run, phase: str) -> None:
        """Phase 10 (role matrix 3a, rule 6): an assess run's view of its bid carries no
        price, other bids or people's scores, before or after it submits."""
        found = await self._call(
            mcp, run, "get_bid_for_assessment", {"bid_id": run.bid_id}, phase=f"probe-{phase}"
        )
        if found.is_error:
            return
        bid = found.content.get("bid") or {}
        previous = found.content.get("previous") or {}
        self.observations.blind(
            run.run_id,
            {
                "tool": "get_bid_for_assessment",
                "phase": phase,
                "keys": sorted(found.content),
                "bid_keys": sorted(bid),
                "documents": len(found.content.get("documents") or []),
                "previous": bool(previous),
                "previous_keys": sorted(previous),
            },
        )

    async def _stray(self, mcp: McpClient, run: Run) -> None:
        """c22: try what an agent steered by planted text might, recording the codes."""
        idea = await self._call(mcp, run, "get_idea", {"idea": run.idea}, phase="stray")
        project = ((idea.content.get("idea") or {}).get("project") or {}).get("slug")
        prefix, number = IDEA_KEY.fullmatch(run.idea).groups()  # type: ignore[union-attr]
        other_section = "summary" if run.section_key != "summary" else "problem"
        attempts: list[tuple[str, str, dict[str, Any]]] = [
            ("add_comment", "add_comment", {"idea": run.idea, "body_md": "A stray comment."}),
            (
                "create_idea",
                "create_idea",
                {"project": project or "none", "title": "A stray idea", "summary": "Stray."},
            ),
            ("get_idea_next", "get_idea", {"idea": f"{prefix}-{int(number) + 1}"}),
            (
                "propose_other_section",
                "propose_proposal_section",
                {"idea": run.idea, "section_key": other_section, "body_md": "Stray text."},
            ),
        ]
        for kind, tool in WRITE_TOOLS.items():
            if kind != run.kind and tool != "propose_proposal_section":
                attempts.append((tool, tool, stray_write_arguments(tool, run.idea)))
        # Phase 10 (c22): another bid's tools; an assess run reads nothing but its bid.
        attempts.append(("get_bid_other", "get_bid_for_assessment", {"bid_id": PLACEHOLDER_ID}))
        if run.kind == "assess_bid":
            attempts.append(("get_idea", "get_idea", {"idea": run.idea}))
            attempts.append(("get_rubric", "get_rubric", {"idea": run.idea}))
            attempts.append(("get_proposal", "get_proposal", {"idea": run.idea}))
        if run.kind == "research":
            # Soundings' 8b guest review M1: a research run's note reaches the idea's guest
            # researcher, so it may read neither the proposal nor the rubric.
            attempts.append(("get_proposal", "get_proposal", {"idea": run.idea}))
            attempts.append(("get_rubric", "get_rubric", {"idea": run.idea}))
        for attempt, tool, arguments in attempts:
            result = await self._call(mcp, run, tool, arguments, phase="stray")
            self.observations.stray(run.run_id, attempt, result.error_code)
        projects = await self._call(mcp, run, "list_projects", {}, phase="stray")
        self.observations.stray(
            run.run_id,
            "list_projects",
            projects.error_code
            or ",".join(p.get("slug", "?") for p in projects.content.get("projects") or []),
        )
        ideas = await self._call(mcp, run, "search_ideas", {"limit": 50}, phase="stray")
        self.observations.stray(
            run.run_id,
            "search_ideas",
            ideas.error_code
            or ",".join(i.get("key", "?") for i in ideas.content.get("items") or []),
        )

    async def _late_write(self, run: Run, cancelled: asyncio.Event) -> None:
        """Ignore the end of the run: after its cancel (the worker sends one at a cancel
        request, the deadline and shutdown), wait, then try to save a result anyway."""
        try:
            await cancelled.wait()
            await asyncio.sleep(self.settings.late_delay)
            async with self._client() as mcp:
                tool = WRITE_TOOLS[run.kind]
                if run.kind == "evaluate":
                    rubric = await mcp.call("get_rubric", with_run(run, {"idea": run.idea}))
                    self.observations.tool_call(run.run_id, "get_rubric", rubric.error_code, "late")
                    arguments = evaluation_arguments(
                        run.idea, rubric.content.get("criteria") or [_placeholder_criterion()]
                    )
                elif run.kind == "research":
                    arguments = research_arguments(run.idea)
                elif run.kind == "assess_bid":
                    arguments = stray_write_arguments(tool, run.idea, bid_id=run.bid_id)
                else:
                    arguments = {
                        "idea": run.idea,
                        "section_key": run.section_key,
                        "body_md": "Late text.",
                    }
                result = await mcp.call(tool, with_run(run, arguments))
                self.observations.tool_call(run.run_id, tool, result.error_code, "late")
                self.observations.late(run.run_id, tool, result.error_code)
        except McpTransportError as error:
            self.observations.late(run.run_id, WRITE_TOOLS[run.kind], f"transport: {error}")
        except asyncio.CancelledError:
            raise


def _placeholder_criterion() -> dict[str, Any]:
    return {"id": "00000000-0000-0000-0000-000000000000", "name": "Unknown"}


def evaluation_arguments(idea: str, criteria: list[dict[str, Any]]) -> dict[str, Any]:
    """``submit_evaluation``: every criterion scored by its position (3, 4, 5, 1, 2, ...),
    a rationale naming the criterion and the idea, two well-formed (fake) sources."""
    scores = []
    for position, criterion in enumerate(criteria):
        score = 1 + (position + 2) % 5
        name = _cut(str(criterion.get("name") or "criterion"), 80)
        scores.append(
            {
                "criterion_id": criterion["id"],
                "score": score,
                "comment": _cut(
                    f"{RATIONALE_MARKER}: {name} for {idea} gets {score} of 5 from its position "
                    f"({position + 1}) in the rubric. Deterministic fake agent, not a real "
                    "assessment.",
                    1000,
                ),
                "sources": [
                    {
                        "title": _cut(f"Fake source {n} on {name}", 200),
                        "url": f"{SOURCE_BASE}/{idea.lower()}/{criterion['id']}/{n}",
                    }
                    for n in (1, 2)
                ],
            }
        )
    return {
        "idea": idea,
        "scores": scores,
        "recommendation": "maybe",
        "comment": (
            f"{RATIONALE_MARKER}: summary for {idea} from Soundings' deterministic fake agent "
            "(scores follow the rubric order)."
        ),
        "submit": True,
    }


def research_arguments(idea: str) -> dict[str, Any]:
    body = (
        f"## Research note on {idea}\n\n"
        "Written by Soundings' deterministic fake agent: the findings and sources are "
        "placeholders for tests, not research.\n\n"
        "### Findings\n\n"
        "- Similar tools exist; none fits this team's workflow exactly [1].\n"
        "- The main cost is people's time, not licences [2].\n\n"
        "### Open questions\n\n"
        "- Who would own it after the pilot? [3]\n"
    )
    return {
        "idea": idea,
        "body_md": body,
        "sources": [
            {
                "title": f"Fake research source {n}",
                "url": f"{SOURCE_BASE}/research/{idea.lower()}/{n}",
            }
            for n in (1, 2, 3)
        ],
    }


def draft_arguments(idea: str, section: dict[str, Any]) -> dict[str, Any]:
    existing = str(section.get("body_md") or "").rstrip()
    addition = (
        f"_Draft by Soundings' fake agent for {idea}: a placeholder paragraph for the "
        f"{section.get('title') or section.get('key')} section, to accept or discard._"
    )
    body = f"{existing}\n\n{addition}" if existing else addition
    arguments: dict[str, Any] = {
        "idea": idea,
        "section_key": section.get("key"),
        "body_md": body[-20_000:],
    }
    if isinstance(section.get("version"), int):
        arguments["base_version"] = section["version"]
    return arguments


def stray_write_arguments(tool: str, idea: str, *, bid_id: str | None = None) -> dict[str, Any]:
    if tool == "submit_evaluation":
        return {"idea": idea, "scores": [], "submit": False}
    if tool == "submit_bid_assessment":
        # Well-formed (so Soundings checks the run, not the shape): one score of 0.
        return {
            "bid_id": bid_id or PLACEHOLDER_ID,
            "scores": [{"question_id": PLACEHOLDER_ID, "score": 0, "rationale": "A stray score."}],
            "findings": [],
        }
    return {"idea": idea, "body_md": "A stray note.", "sources": []}


def passages(text: str) -> list[str]:
    """The quotable passages of a document's text, in order: its lines and sentences with
    whitespace normalised (as Soundings compares quotes), cut to at most ``QUOTE_MAX``
    characters at a word boundary, kept from ``QUOTE_MIN`` characters up. Each is a
    substring of the document's normalised text, so Soundings finds it."""
    found: list[str] = []
    for line in text.splitlines():
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            passage = " ".join(sentence.split())
            if len(passage) > QUOTE_MAX:
                passage = passage[:QUOTE_MAX].rsplit(" ", 1)[0]
            if len(passage) >= QUOTE_MIN and passage not in found:
                found.append(passage)
    return found


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{5,}", text.lower()))


def assessment_arguments(
    bid_id: str,
    call: dict[str, Any],
    document_ids: list[str],
    texts: dict[str, str],
    *,
    invent: bool = False,
    not_met: bool = False,
) -> dict[str, Any]:
    """``submit_bid_assessment``: every score question of every section, in order, scored
    by its position (3, 4, 5, 1, 2, ...) with one quote from the documents' text (taken in
    turn); a question gets 0 and no quote when no document has text. Every must-have it
    was shown: a required document with a readable linked file is met (a quote from that
    file), linked but unreadable (or restricted) unclear, with no file not met; a
    confirmation met when a passage shares a word of five letters or more with it (that
    passage), else unclear. ``invent``: the first quote is replaced by one that is in no
    document; ``not_met``: the first must-have is found not met."""
    pool = [
        (document_id, passage)
        for document_id in document_ids
        for passage in passages(texts.get(document_id, ""))
    ]
    scores: list[dict[str, Any]] = []
    position = 0
    for section in call.get("sections") or []:
        for question in section.get("questions") or []:
            if pool:
                score = 1 + (position + 2) % 5
                document_id, quote = pool[position % len(pool)]
                evidence = [{"document_id": document_id, "quote": quote}]
            else:
                score, evidence = 0, []
            scores.append(
                {
                    "question_id": question["id"],
                    "score": score,
                    "rationale": _cut(
                        f"{RATIONALE_MARKER}: question {position + 1} of the call gets "
                        f"{score} of 5 from its position. Deterministic fake agent, not a "
                        "real assessment.",
                        1000,
                    ),
                    "evidence": evidence,
                }
            )
            position += 1
    findings: list[dict[str, Any]] = []
    for index, must_have in enumerate(call.get("must_haves") or []):
        linked = [str(d) for d in must_have.get("document_ids") or []]
        readable = [d for d in linked if passages(texts.get(d, ""))]
        finding, evidence = "unclear", []
        if not_met and index == 0:
            finding = "not_met"
        elif must_have.get("kind") == "document":
            if readable:
                finding = "met"
                evidence = [{"document_id": readable[0], "quote": passages(texts[readable[0]])[0]}]
            elif not linked and not must_have.get("restricted_document_count"):
                finding = "not_met"
        else:
            wanted = _words(str(must_have.get("text") or ""))
            match = next(((d, p) for d, p in pool if wanted & _words(p)), None)
            if match is not None:
                finding = "met"
                evidence = [{"document_id": match[0], "quote": match[1]}]
        findings.append(
            {
                "must_have_id": must_have["id"],
                "finding": finding,
                "rationale": _cut(
                    f"{RATIONALE_MARKER}: must-have {index + 1} is {finding} by the fake "
                    "agent's fixed rules (not a real check).",
                    1000,
                ),
                "evidence": evidence,
            }
        )
    if invent:
        target = next((s for s in scores if s["evidence"]), None)
        if target is not None:
            target["evidence"][0] = {
                "document_id": target["evidence"][0]["document_id"],
                "quote": INVENTED_QUOTE,
            }
        elif scores and document_ids:
            scores[0]["evidence"] = [{"document_id": document_ids[0], "quote": INVENTED_QUOTE}]
    return {"bid_id": bid_id, "scores": scores, "findings": findings}
