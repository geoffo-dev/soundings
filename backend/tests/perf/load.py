"""Load test for a running Soundings API seeded by ``tests.perf.seed_large``.

``--users`` virtual people (default 20, signed in through the dev login) each loop over
the screens they would use: load the app, open Big Ideas as a board or a list, scroll,
filter and sort, search, open an idea and its evaluations, the evaluate sheet, My work,
the inbox and (admins) the audit log, and now and then write (comment, vote, watch,
save an evaluation draft, edit a summary, add an idea). The requests of one screen go
out together, as the SPA sends them. Between screens each person thinks for
``--think`` seconds (default 0.5-2.0, uniform; ``--think 0`` is a stress test).

Every request is timed by the name of the operation it exercises; the report gives
p50/p95/p99/max per name against the budgets (reads p95 < 150 ms, writes p95 < 250 ms),
throughput, errors, and the resident memory of the API's and worker's process groups
(``--api-pid`` / ``--worker-pid``: pid files written by e2e/scripts/start-stack.sh).
``--json PATH`` writes the raw numbers. Exit status 1 when a budget is missed
(``--no-fail`` reports only).

    uv run python -m tests.perf.load --base-url http://localhost:8320 --duration 120

Each person keeps to their own rows for writes (their own comments, votes, drafts and
the ideas they create), so the data set stays what the seed made, give or take.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from statistics import quantiles
from typing import Any

import httpx

__all__ = ["main", "run_load"]

API = "/api/v1"
READ_BUDGET_MS = 150.0
WRITE_BUDGET_MS = 250.0
BIG = "big-ideas"
SEARCH_WORDS = ("pricing", "refunds", "kiosk", "BIG-42", "chat", "returns", "onboard", "gift")
FILTERS: tuple[dict[str, Any], ...] = (
    {"sort": "-score"},
    {"sort": "title"},
    {"sort": "-votes"},
    {"status": ["evaluating", "shortlisted"]},
    {"q": "pricing"},
    {"tag": ["ux-1"]},
    {"high_disagreement": "true"},
    {"needs_evaluators": "true"},
)
# A team of 20 on Big Ideas: Alice (platform admin), two project admins, the person who
# owes 1,000 evaluations, a viewer and members.
DEFAULT_PEOPLE = (
    "alice@example.com",
    "perf02@example.com",
    "perf03@example.com",
    "perf01@example.com",
    "perf04@example.com",
    *(f"perf{n:02d}@example.com" for n in range(6, 21)),
)


@dataclass(slots=True)
class Sample:
    name: str
    kind: str  # read, write, screen (one screen's requests, together) or probe
    ms: float
    status: int

    @property
    def write(self) -> bool:
        return self.kind == "write"


@dataclass(slots=True)
class Person:
    email: str
    client: httpx.AsyncClient
    rng: random.Random
    samples: list[Sample]
    admin_of: list[str] = field(default_factory=list)
    platform_admin: bool = False
    viewer: bool = False
    due: list[str] = field(default_factory=list)
    criteria: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    big_count: int = 10_000

    async def call(
        self, name: str, method: str, url: str, *, write: bool = False, **kwargs: Any
    ) -> httpx.Response | None:
        kind = "write" if write else "read"
        started = time.perf_counter()
        try:
            response = await self.client.request(method, url, **kwargs)
        except httpx.HTTPError:
            self.samples.append(Sample(name, kind, (time.perf_counter() - started) * 1000, 0))
            return None
        self.samples.append(
            Sample(name, kind, (time.perf_counter() - started) * 1000, response.status_code)
        )
        return response

    async def get(self, name: str, url: str, **params: Any) -> httpx.Response | None:
        return await self.call(name, "GET", f"{API}{url}", params=params or None)

    async def screen(self, name: str, *calls: Awaitable[httpx.Response | None]) -> list[Any]:
        """The requests of one screen, sent together; also timed as a whole ("screen")."""
        started = time.perf_counter()
        responses = list(await asyncio.gather(*calls))
        failed = [r for r in responses if r is None or r.status_code >= 400]
        status = 0 if failed else 200
        self.samples.append(
            Sample(f"screen: {name}", "screen", (time.perf_counter() - started) * 1000, status)
        )
        return responses

    def idea(self) -> str:
        return f"BIG-{self.rng.randint(1, self.big_count)}"


# --- Screens ------------------------------------------------------------------------------
async def shell(p: Person) -> None:
    """A cold load of any page: what the app shell fetches before the screen's own data.
    Phase 7: the sidebar's badges come from ``/me/work/counts`` (C1) and its review
    counts from ``/projects`` (C2), no longer from My work and one moderation request
    per project."""
    await p.screen(
        "app shell (cold load)",
        p.get("auth.me", "/auth/me"),
        p.get("branding", "/branding"),
        p.get("projects.list", "/projects"),
        p.get("me.work.counts", "/me/work/counts"),
        p.get("notifications.summary", "/me/notifications/summary"),
    )


async def board(p: Person) -> None:
    await p.screen(
        "board",
        p.get("project.get", f"/projects/{BIG}"),
        p.get("board", f"/projects/{BIG}/board", limit=50),
        p.get("project.members", f"/projects/{BIG}/members"),
        p.get("project.tags", f"/projects/{BIG}/tags"),
    )
    # Scroll one column ("Load more" / infinite scroll in a column).
    status = p.rng.choice(["new", "evaluating", "closed"])
    await p.get("list (board column more)", f"/projects/{BIG}/ideas", status=status, limit=50)


async def list_view(p: Person) -> None:
    first, *_ = await p.screen(
        "list",
        p.get("project.get", f"/projects/{BIG}"),
        p.get("list", f"/projects/{BIG}/ideas", limit=100),
        p.get("project.members", f"/projects/{BIG}/members"),
        p.get("project.tags", f"/projects/{BIG}/tags"),
    )
    cursor = first.json().get("next_cursor") if first is not None and first.is_success else None
    for _ in range(p.rng.randint(1, 3)):  # scroll a few pages
        if not cursor:
            break
        page = await p.get("list (next page)", f"/projects/{BIG}/ideas", limit=100, cursor=cursor)
        cursor = page.json().get("next_cursor") if page is not None and page.is_success else None


async def filter_sort(p: Person) -> None:
    query = dict(p.rng.choice(FILTERS))
    name = "list " + ",".join(f"{k}={v}" for k, v in query.items())
    if p.rng.random() < 0.5:
        await p.get(name, f"/projects/{BIG}/ideas", limit=100, **query)
    else:
        await p.get("board " + name[5:], f"/projects/{BIG}/board", limit=50, **query)


async def search(p: Person) -> None:
    word = p.rng.choice(SEARCH_WORDS)
    for length in (2, len(word)):  # the palette searches as you type (debounced)
        await p.get("search", "/search", q=word[:length])


async def idea_page(p: Person) -> None:
    key = p.idea()
    await p.screen(
        "idea page",
        p.get("idea.get", f"/ideas/{key}"),
        p.get("idea.ai_runs", f"/ideas/{key}/ai-runs", limit=20),
        p.get("idea.activity", f"/ideas/{key}/activity", limit=50),
        p.get("project.get", f"/projects/{BIG}"),
        p.call(
            "notifications.read_all (idea)",
            "POST",
            f"{API}/me/notifications/read-all",
            params={"idea": key},
            write=True,
        ),
    )
    if p.rng.random() < 0.5:
        await p.get("idea.evaluations", f"/ideas/{key}/evaluations")


async def evaluate_sheet(p: Person) -> None:
    if not p.due:
        return
    key = p.rng.choice(p.due)
    await p.screen(
        "evaluate sheet",
        p.get("idea.get", f"/ideas/{key}"),
        p.get("evaluation.me", f"/ideas/{key}/evaluations/me"),
    )


async def my_work(p: Person) -> None:
    await p.get("me.work", "/me/work")


async def inbox(p: Person) -> None:
    page = await p.get("notifications.list", "/me/notifications", limit=30)
    cursor = page.json().get("next_cursor") if page is not None and page.is_success else None
    if cursor:
        await p.get("notifications.list (next page)", "/me/notifications", limit=30, cursor=cursor)


async def audit(p: Person) -> None:
    if not p.platform_admin:
        return
    await p.screen(
        "audit log",
        p.get("projects.list (archived)", "/projects", include_archived="true"),
        p.get("admin.audit", "/admin/audit", limit=50),
    )


async def people_picker(p: Person) -> None:
    await p.get("users.search", "/users", q=p.rng.choice(["a", "no", "pat", "ali"]), project=BIG)


async def write(p: Person) -> None:
    if p.viewer:
        return
    key = p.idea()
    choice = p.rng.random()
    if choice < 0.3:
        await p.call(
            "comment.create",
            "POST",
            f"{API}/ideas/{key}/comments",
            write=True,
            json={"body_md": "Load test: could we pilot this in one region first?"},
        )
    elif choice < 0.5:
        await p.call("idea.vote", "PUT", f"{API}/ideas/{key}/vote", write=True)
        await p.call("idea.unvote", "DELETE", f"{API}/ideas/{key}/vote", write=True)
    elif choice < 0.65:
        await p.call("idea.watch", "PUT", f"{API}/ideas/{key}/watch", write=True)
        await p.call("idea.unwatch", "DELETE", f"{API}/ideas/{key}/watch", write=True)
    elif choice < 0.85 and p.due:
        target = p.rng.choice(p.due)
        mine = await p.get("evaluation.me", f"/ideas/{target}/evaluations/me")
        if mine is None or not mine.is_success:
            return
        scores = [{"criterion_id": c, "score": p.rng.randint(1, 5)} for c in p.criteria[:2]]
        await p.call(
            "evaluation.save_draft",
            "PUT",
            f"{API}/ideas/{target}/evaluations/me",
            write=True,
            json={"scores": scores, "submit": False},
        )
    elif choice < 0.95 or not p.created:
        made = await p.call(
            "idea.create",
            "POST",
            f"{API}/projects/{BIG}/ideas",
            write=True,
            json={"title": "Load-test idea", "summary": "Created by tests/perf/load.py."},
        )
        if made is not None and made.is_success:
            p.created.append(made.json()["key"])
    else:  # edit an idea of one's own (the submitter may)
        await p.call(
            "idea.update",
            "PATCH",
            f"{API}/ideas/{p.rng.choice(p.created)}",
            write=True,
            json={"summary": f"Edited by the load test at {time.time():.0f}."},
        )


SCREENS: tuple[tuple[Callable[[Person], Awaitable[None]], int], ...] = (
    (shell, 6),
    (board, 8),
    (list_view, 8),
    (filter_sort, 10),
    (search, 6),
    (idea_page, 16),
    (evaluate_sheet, 4),
    (my_work, 6),
    (inbox, 5),
    (audit, 2),
    (people_picker, 2),
    (write, 10),
)


# --- Running ------------------------------------------------------------------------------
async def sign_in(base_url: str, email: str, users: list[dict[str, Any]], seed: int) -> Person:
    user = next((u for u in users if u["email"] == email), None)
    if user is None:
        raise SystemExit(f"no dev-login user {email}: seed with tests.perf.seed_large first")
    client = httpx.AsyncClient(base_url=base_url, timeout=30, http2=False)
    response = await client.post(f"{API}/auth/dev/login", json={"user_id": user["id"]})
    response.raise_for_status()
    client.headers["X-CSRF-Token"] = client.cookies["soundings_csrf"]
    person = Person(email=email, client=client, rng=random.Random(seed), samples=[])  # noqa: S311
    me = (await client.get(f"{API}/auth/me")).json()
    person.platform_admin = bool(me.get("is_platform_admin"))
    members = (await client.get(f"{API}/projects/{BIG}/members")).json()
    mine = [m for m in members if m["user"]["id"] == user["id"]]
    person.viewer = bool(mine) and mine[0]["role"] == "viewer"
    projects = (await client.get(f"{API}/projects")).json()
    items = projects["items"] if isinstance(projects, dict) else projects
    person.admin_of = [
        p["slug"] for p in items if person.platform_admin or p.get("my_role") == "admin"
    ]
    project = (await client.get(f"{API}/projects/{BIG}")).json()
    person.criteria = [criterion["id"] for criterion in project.get("rubric", [])]
    work = (await client.get(f"{API}/me/work")).json()
    person.due = [item["idea"]["key"] for item in work.get("evaluations_due", [])][:200]
    big = next((p for p in items if p["slug"] == BIG), None)
    if big is not None:
        person.big_count = max(1, int(big.get("idea_count") or 10_000))
    return person


async def virtual_user(person: Person, deadline: float, think: tuple[float, float]) -> None:
    screens, weights = zip(*SCREENS, strict=True)
    while time.monotonic() < deadline:
        screen = person.rng.choices(screens, weights=weights)[0]
        await screen(person)
        if think[1] > 0:
            await asyncio.sleep(person.rng.uniform(*think))


def rss_mb(pid_file: Path | None) -> float | None:
    """Resident memory of a process group started by start-stack.sh (uv, the app, children)."""
    if pid_file is None or not pid_file.exists():
        return None
    pid = pid_file.read_text().strip()
    out = subprocess.run(  # noqa: S603 - fixed argv, the pid from our own pid file
        ["ps", "-o", "rss=", "-g", pid],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return round(sum(int(v) for v in out.split()) / 1024, 1)


def cpu_seconds(pid_file: Path | None) -> float | None:
    """User + system CPU seconds used so far by that process group."""
    if pid_file is None or not pid_file.exists():
        return None
    out = subprocess.run(  # noqa: S603 - fixed argv, the pid from our own pid file
        ["ps", "-o", "pid=", "-g", pid_file.read_text().strip()],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    ticks = 0
    for pid in out.split():
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        except OSError:
            continue
        ticks += int(fields[11]) + int(fields[12])  # utime, stime
    return ticks / 100


def container_cpu_seconds(container: str | None) -> float | None:
    """CPU seconds used by a Docker container (cgroup v1 cpuacct or v2 cpu.stat)."""
    if not container:
        return None
    out = subprocess.run(  # noqa: S603 - fixed argv
        [  # noqa: S607
            "docker",
            "exec",
            container,
            "sh",
            "-c",
            "cat /sys/fs/cgroup/cpuacct/cpuacct.usage 2>/dev/null"
            " || awk '/usage_usec/ {print $2 * 1000}' /sys/fs/cgroup/cpu.stat",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return int(float(out)) / 1e9 if out else None


def percentile(samples: list[float], q: int) -> float:
    if len(samples) == 1:
        return samples[0]
    return quantiles(samples, n=100, method="inclusive")[q - 1]


def summarise(samples: list[Sample], seconds: float) -> dict[str, Any]:
    by_name: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        by_name[sample.name].append(sample)
    rows = []
    for name, group in sorted(by_name.items()):
        ms = [s.ms for s in group]
        kind = group[0].kind
        budget = {"write": WRITE_BUDGET_MS, "read": READ_BUDGET_MS}.get(kind)
        p95 = percentile(ms, 95)
        errors = [s.status for s in group if s.status == 0 or s.status >= 400]
        rows.append(
            {
                "name": name,
                "kind": kind,
                "n": len(ms),
                "p50": round(percentile(ms, 50), 1),
                "p95": round(p95, 1),
                "p99": round(percentile(ms, 99), 1),
                "max": round(max(ms), 1),
                "errors": len(errors),
                "error_statuses": sorted(set(errors)),
                "budget": budget,
                "ok": (budget is None or p95 < budget) and not errors,
            }
        )
    reads = [s.ms for s in samples if s.kind == "read"]
    writes = [s.ms for s in samples if s.kind == "write"]
    return {
        "requests": len(reads) + len(writes),
        "seconds": round(seconds, 1),
        "rps": round((len(reads) + len(writes)) / seconds, 1),
        "reads_p95": round(percentile(reads, 95), 1) if reads else None,
        "writes_p95": round(percentile(writes, 95), 1) if writes else None,
        "rows": rows,
    }


def table(report: dict[str, Any]) -> str:
    lines = [
        f"{'operation':44} {'kind':5} {'n':>5} {'p50':>7} {'p95':>7} {'p99':>7} {'max':>7}  ok",
    ]
    order = {"probe": 0, "screen": 1, "read": 2, "write": 3}
    for row in sorted(report["rows"], key=lambda r: (order.get(r["kind"], 9), -r["p95"])):
        flag = "yes" if row["ok"] else f"NO ({row['errors']} errors)" if row["errors"] else "NO"
        lines.append(
            f"{row['name'][:44]:44} {row['kind']:5} {row['n']:5d} {row['p50']:7.1f} "
            f"{row['p95']:7.1f} {row['p99']:7.1f} {row['max']:7.1f}  {flag}"
        )
    lines.append(
        f"{report['requests']} requests in {report['seconds']} s ({report['rps']}/s); "
        f"reads p95 {report['reads_p95']} ms, writes p95 {report['writes_p95']} ms; "
        f"memory MB {report.get('memory_mb')}; CPU cores {report.get('cpu')}"
    )
    return "\n".join(lines)


async def run_load(
    base_url: str,
    *,
    people: tuple[str, ...] = DEFAULT_PEOPLE,
    users: int = 20,
    duration: float = 120.0,
    think: tuple[float, float] = (0.5, 2.0),
    seed: int = 7,
    warmup: float = 10.0,
    api_pid: Path | None = None,
    worker_pid: Path | None = None,
    pg_container: str | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as anonymous:
        listed = (await anonymous.get(f"{API}/auth/dev/users")).json()
    chosen = (people * (users // len(people) + 1))[:users]
    team = [await sign_in(base_url, email, listed, seed + n) for n, email in enumerate(chosen)]
    memory: dict[str, Any] = {"api_before": rss_mb(api_pid), "worker_before": rss_mb(worker_pid)}
    cpu: dict[str, Any] = {}
    try:
        if warmup > 0:  # fill caches and the pool; discarded
            end = time.monotonic() + warmup
            await asyncio.gather(*(virtual_user(p, end, think) for p in team))
            for person in team:
                person.samples.clear()
        started = time.monotonic()
        deadline = started + duration
        cpu_before = (cpu_seconds(api_pid), container_cpu_seconds(pg_container))
        peak = {"api": memory["api_before"] or 0.0, "worker": memory["worker_before"] or 0.0}

        async def sample_memory() -> None:
            while time.monotonic() < deadline:
                await asyncio.sleep(2)
                peak["api"] = max(peak["api"], rss_mb(api_pid) or 0.0)
                peak["worker"] = max(peak["worker"], rss_mb(worker_pid) or 0.0)

        probes: list[Sample] = []

        async def probe() -> None:
            """/healthz every 100 ms: no database, so its latency is the event loop's lag."""
            async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
                while time.monotonic() < deadline:
                    started_at = time.perf_counter()
                    response = await client.get("/healthz")
                    ms = (time.perf_counter() - started_at) * 1000
                    probes.append(
                        Sample("probe: /healthz (loop lag)", "probe", ms, response.status_code)
                    )
                    await asyncio.sleep(0.1)

        await asyncio.gather(
            sample_memory(), probe(), *(virtual_user(p, deadline, think) for p in team)
        )
        elapsed = time.monotonic() - started
        cpu_after = (cpu_seconds(api_pid), container_cpu_seconds(pg_container))
        for name, before, after in zip(("api", "postgres"), cpu_before, cpu_after, strict=True):
            if before is not None and after is not None:
                cpu[f"{name}_cores"] = round((after - before) / elapsed, 2)
    finally:
        for person in team:
            await person.client.aclose()
    memory.update(api_peak=peak["api"], worker_peak=peak["worker"], api_after=rss_mb(api_pid))
    report = summarise([s for p in team for s in p.samples] + probes, elapsed)
    report.update(users=users, think=list(think), memory_mb=memory, cpu=cpu)
    return report


def isolated_calls(p: Person) -> list[tuple[str, str, dict[str, Any]]]:
    """One request per operation, for service times without contention."""
    key = "BIG-9900"  # an idea with 60 comments (one in a hundred has)
    due = p.due[0] if p.due else key
    calls: list[tuple[str, str, dict[str, Any]]] = [
        ("auth.me", "/auth/me", {}),
        ("branding", "/branding", {}),
        ("projects.list", "/projects", {}),
        ("notifications.summary", "/me/notifications/summary", {}),
        ("me.work", "/me/work", {}),
        ("me.work.counts", "/me/work/counts", {}),
        ("me.evaluations_due", "/me/evaluations-due", {}),
        ("project.get", f"/projects/{BIG}", {}),
        ("project.members", f"/projects/{BIG}/members", {}),
        ("project.tags", f"/projects/{BIG}/tags", {}),
        ("board", f"/projects/{BIG}/board", {"limit": 50}),
        ("board sort=-score", f"/projects/{BIG}/board", {"limit": 50, "sort": "-score"}),
        ("list", f"/projects/{BIG}/ideas", {"limit": 100}),
        ("list sort=-score", f"/projects/{BIG}/ideas", {"limit": 100, "sort": "-score"}),
        ("list sort=title", f"/projects/{BIG}/ideas", {"limit": 100, "sort": "title"}),
        ("list q=pricing", f"/projects/{BIG}/ideas", {"limit": 100, "q": "pricing"}),
        (
            "list status=evaluating",
            f"/projects/{BIG}/ideas",
            {"limit": 100, "status": "evaluating"},
        ),
        (
            "list needs_evaluators",
            f"/projects/{BIG}/ideas",
            {"limit": 100, "needs_evaluators": "true"},
        ),
        ("search q=pricing", "/search", {"q": "pricing"}),
        ("search q=pr", "/search", {"q": "pr"}),
        ("idea.get", f"/ideas/{key}", {}),
        ("idea.activity (60 comments)", f"/ideas/{key}/activity", {"limit": 50}),
        ("idea.evaluations", f"/ideas/{key}/evaluations", {}),
        ("idea.ai_runs", f"/ideas/{key}/ai-runs", {"limit": 20}),
        ("evaluation.me", f"/ideas/{due}/evaluations/me", {}),
        ("notifications.list", "/me/notifications", {"limit": 30}),
        ("users.search", "/users", {"q": "a", "project": BIG}),
        ("me.owned_ideas", "/me/owned-ideas", {}),
    ]
    calls += [
        (f"moderation {s} (limit 1)", f"/projects/{s}/moderation", {"limit": 1})
        for s in p.admin_of[:1]
    ]
    if p.platform_admin:
        calls += [
            ("admin.audit", "/admin/audit", {"limit": 50}),
            ("admin.users", "/admin/users", {"limit": 50}),
        ]
    return calls


async def run_isolated(
    base_url: str, people: tuple[str, ...], runs: int, seed: int
) -> dict[str, Any]:
    """Each operation ``runs`` times in a row by one person at a time (service time)."""
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as anonymous:
        listed = (await anonymous.get(f"{API}/auth/dev/users")).json()
    out: dict[str, Any] = {}
    for email in people:
        person = await sign_in(base_url, email, listed, seed)
        try:
            for name, url, params in isolated_calls(person):
                for _ in range(3):
                    await person.client.get(f"{API}{url}", params=params)
                person.samples = []
                for _ in range(runs):
                    await person.get(name, url, **params)
                out.setdefault(email, []).extend(person.samples)
        finally:
            await person.client.aclose()
    return {email: summarise(samples, 1.0) for email, samples in out.items()}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8320")
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--duration", type=float, default=120.0, help="seconds measured")
    parser.add_argument("--warmup", type=float, default=10.0, help="seconds discarded first")
    parser.add_argument(
        "--think", default="0.5-2.0", help="seconds between screens, 'lo-hi' or '0' (stress)"
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--api-pid", type=Path, help="e2e/perf/.stack/api.pid")
    parser.add_argument("--worker-pid", type=Path, help="e2e/perf/.stack/worker.pid")
    parser.add_argument("--pg-container", help="Postgres container, for its CPU (p7-perf-pg)")
    parser.add_argument("--json", type=Path, help="write the report here")
    parser.add_argument("--no-fail", action="store_true", help="exit 0 even over budget")
    parser.add_argument(
        "--isolated", type=int, metavar="RUNS", help="service times: RUNS calls per operation"
    )
    args = parser.parse_args(argv)
    if args.isolated:
        people = ("alice@example.com", "perf01@example.com")
        reports = asyncio.run(run_isolated(args.base_url, people, args.isolated, args.seed))
        for email, report in reports.items():
            sys.stdout.write(f"\n# {email} (one request at a time)\n" + table(report) + "\n")
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(reports, indent=2) + "\n")
        return
    lo, _, hi = args.think.partition("-")
    think = (float(lo), float(hi or lo))
    report = asyncio.run(
        run_load(
            args.base_url,
            users=args.users,
            duration=args.duration,
            think=think,
            seed=args.seed,
            warmup=args.warmup,
            api_pid=args.api_pid,
            worker_pid=args.worker_pid,
            pg_container=args.pg_container,
        )
    )
    sys.stdout.write(table(report) + "\n")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    missed = [row["name"] for row in report["rows"] if not row["ok"]]
    if missed and not args.no_fail:
        sys.stdout.write(f"over budget or failing: {', '.join(missed)}\n")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
