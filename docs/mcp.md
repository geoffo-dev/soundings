# Connecting MCP clients to Soundings

Soundings runs an [MCP](https://modelcontextprotocol.io) server at `/mcp` on the same
address as the app (for example `https://ideas.example.com/mcp`; `http://localhost:8000/mcp`
with `make demo` or `make -C backend dev`). An MCP client, such as Claude Code, Claude
Desktop, an assistant in your editor or a kagent agent, uses it to search ideas, read
proposals, comment and submit evaluations **as you**, through a personal API key.

This page is for people connecting a client. Operators: [operator-guide.md](operator-guide.md#api-keys-and-mcp-phase-5).
The precise contract is [contract-phase5.md §3.5 and §4](api/contract-phase5.md#35-the-mcp-endpoint-transport)
(Phase 6's additions: [contract-phase6.md §4](api/contract-phase6.md#4-mcp-additions)).
Soundings' own AI agents, which kagent runs for "Ask AI to evaluate", "Research this" and
"Draft with AI", use this server too, with keys of their own: [section 5](#5-soundings-ai-agents-kagent).

## 1. Create a key

In Soundings, open **Settings → API keys** and choose **Create key**:

| Field | What to pick |
|---|---|
| Name | What it is for, e.g. "Claude Code on my laptop" (unique among your keys) |
| Scopes | A preset: **Read with an assistant** (`read`, `mcp`: search and read), **Evaluate with an assistant** (`read`, `evaluate`, `mcp`: also submit evaluations, which count as yours), **Full access** (all four: also create ideas, comment and suggest proposal text). The `mcp` scope is shown as **AI assistants (MCP)**; on its own it connects but can't use any tool. The dialog says in plain words what the key will be able to do ("This key can …"). |
| Expires | 30 days, 90 days, a year, a date, or never |
| Projects | All projects you can access, or only some (recommended for agents) |

The key (`sdg_` and 53 more characters) is shown **once**: copy it into the client, or
into a password manager, then choose **I've copied it** (closing without copying asks
once more). Soundings keeps only a fingerprint of it. The dialog also shows the examples
below with your key already filled in; Settings → API keys keeps them, with a placeholder
key, under **For developers and AI assistants** (folded by default).

A key never does more than you can do in the app, and only what its scopes allow. It
works until you revoke it or it expires, and it **pauses** when you haven't signed in to
Soundings for 30 days (signing in resumes it). A key made while signed in with the
development login stops when the development login is turned off.

## 2. Connect a client

The server speaks **streamable HTTP, stateless, JSON responses** (no SSE stream, no
session to keep open). Every request carries the key in a header:

```
Authorization: Bearer sdg_…
```

### Claude Code

```sh
claude mcp add --transport http soundings https://ideas.example.com/mcp \
  --header "Authorization: Bearer $SOUNDINGS_API_KEY"
claude mcp get soundings          # Connected
```

That stores the key in `~/.claude.json`. To keep it out of the config, put the server in
a project's `.mcp.json`, which expands environment variables:

```json
{
  "mcpServers": {
    "soundings": {
      "type": "http",
      "url": "https://ideas.example.com/mcp",
      "headers": { "Authorization": "Bearer ${SOUNDINGS_API_KEY}" }
    }
  }
}
```

The same `mcpServers` shape (`type: "http"`, `url`, `headers`) works in other clients that
take HTTP servers with headers, such as many editor assistants.

### Claude Desktop

Claude Desktop's custom connectors sign in with OAuth, which Soundings doesn't offer (keys
are issued in the app), so it connects through the [`mcp-remote`](https://www.npmjs.com/package/mcp-remote)
stdio bridge (needs Node.js). Keep the header in a file only you can read, so the key
stays out of the config and of process lists. In `claude_desktop_config.json` (macOS
`~/Library/Application Support/Claude/`, Windows `%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "soundings": {
      "command": "npx",
      "args": ["-y", "mcp-remote@0.14.3", "https://ideas.example.com/mcp",
               "--header-file", "/Users/you/.config/soundings/mcp-headers.txt"]
    }
  }
}
```

and `mcp-headers.txt` (`chmod 600`) holds one line: `Authorization: Bearer sdg_…`.
`mcp-remote` accepts plain `http://` only for `localhost`; anything else must be https.
Restart Claude Desktop after editing the file.

### Anything else (scripts, SDKs, curl)

Any MCP client that can send a header works. A raw JSON-RPC request, to check a key:

```sh
curl https://ideas.example.com/mcp \
  -H "Authorization: Bearer $SOUNDINGS_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

With the official Python SDK (`mcp` 2.x, which uses `httpx2`):

```python
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

url = "https://ideas.example.com/mcp"
headers = {"Authorization": f"Bearer {key}"}
async with httpx2.AsyncClient(headers=headers) as http:
    async with Client(streamable_http_client(url, http_client=http)) as client:
        result = await client.call_tool("search_ideas", {"awaiting_my_evaluation": True})
        print(result.structured_content)
```

The server supports the protocol versions of the `mcp` SDK it ships with (2024-11-05 to
2025-11-25 and 2026-07-28). Checked against it: Claude Code 2.1.287, `mcp-remote` 0.14.3,
the Python SDK and the Go SDK kagent 0.10 uses.

Then ask, for example, *"Which Soundings ideas are waiting for my evaluation?"* The
client calls `search_ideas` with `awaiting_my_evaluation`, then `get_rubric` and
`get_idea`.

## 3. The tools

Ten tools, always listed (a tool the key's scopes don't allow answers
`insufficient_scope`). Ideas are referenced by key (`CUST-12`, any case) or id; projects
by their URL name (slug). Every tool also takes an optional `run_id`: it is for
Soundings' AI agents only (section 5); people leave it out, and it is ignored for them.

| Tool | Scope | What it does |
|---|---|---|
| `list_projects` | `read` | The projects you can see (inside the key's projects), with your role, the idea count and whether you can create ideas there. Archived ones with `include_archived`. |
| `search_ideas` | `read` | Ideas by `query` (title or summary text, or a key), `project`, `status`, `owner` (`me`, `none`), `awaiting_my_evaluation`, `sort`; 20 a page (`limit` up to 50, `cursor`). Scores follow blind evaluation. |
| `get_idea` | `read` | One idea: description, status, owner, evaluators (invited or submitted), the aggregate and others' evaluations when you may see them, your own evaluation, and the latest comments (`comment_limit`, 10 by default, 20 at most; long comments are cut, `truncated`). Phase 8: `research`, the project's research checklist with this idea's answers (`step`, `items` with `title`, `hint`, `required`, `answer`, who answered and when, `required_open`), or null while the project's research step is off. |
| `get_rubric` | `read` | A project's criteria (by `project` or `idea`) with guidance, weights and which are inverted (a high Effort or Risk score is bad: score what you see). |
| `get_proposal` | `read` | The idea's proposal, section by section in the order of **its project's template** (each with its `key`, `title`, `prompt` (the hint), `body_md` and `version`), or null if none has been started, and whether you may suggest text. |
| `create_idea` | `write` | A new idea in a project, as you (status New; you watch it). |
| `add_comment` | `write` | A comment on an idea, with @mentions as in the app; people are notified as usual. |
| `submit_evaluation` | `evaluate` | Saves your evaluation: a 1-5 score for every criterion, a recommendation (`go`, `maybe`, `no`) and a comment. Submits by default (`submit: false` saves a draft); the arguments replace what was saved. Only if you were asked to evaluate the idea and evaluation is open. |
| `propose_proposal_section` | `write` | Suggests the whole new text of one proposal section, named by its `section_key` from `get_proposal` (a section removed from the template, or a key the project never had, is the tool error `unknown_section`). It is only a suggestion: the idea's owner sees it in the proposal editor and accepts or discards it. A newer suggestion of yours for the same section replaces the older one. |
| `add_research_note` | `write` | Phase 6, **for Soundings' AI agents only**: saves the research note of a "Research this" run (Markdown and up to 20 cited sources) into the idea's activity feed. Anyone else's key gets `forbidden`. |

**Proposal sections and statuses (Phase 8).** Each project has its own proposal template
(1 to 12 sections, edited by its admins). A section's `key` never changes: the eight
built-in sections keep `summary`, `problem`, `solution`, `market`, `cost`, `benefits`,
`risks` and `next_steps` (even when renamed), and a section a project adds gets a key made
from its title (`carbon_impact`, `effort_rollout`; lower-case letters, digits and `_`).
Read the keys from `get_proposal` rather than assuming the eight. A project may also have
a research step: its ideas can then be in status `research` (`search_ideas` takes it as a
`status`; cross-project results order it right after `new`). Moving an idea past Research
needs the required checklist items answered; MCP has no tool that moves an idea or answers
the checklist (people do that in the app, or with a `write` key through the REST API:
`PUT /api/v1/ideas/{key}/research/items/{item_id}`).

Results are structured JSON (`structuredContent`, snake_case, with an `outputSchema` per
tool) plus the same JSON as text. Errors are results with `isError: true`, text
`"<code>: <message>"` and `structuredContent: {code, message}`; the codes are the API's
(`not_found`, `forbidden`, `insufficient_scope`, `validation_error`, `evaluation_closed`,
`too_many_attempts`, …: [contract-phase5 §4.4](api/contract-phase5.md#44-tool-error-codes)).
`not_found` also covers anything the key may not see; `unauthorized` means the key was
revoked or expired, or its owner deactivated, while the call was on its way.

Behind a proxy that adds its own `Authorization: Bearer` header (an OAuth2 or
forward-auth proxy), every request is read as a bad key: operators must not forward such
a header ([operator guide](operator-guide.md#api-keys-and-mcp-phase-5)).

## 4. Safety notes

- **The client is you.** It acts with your permissions at the moment of each call,
  narrowed by the key; if your role changes, the key follows on the next call. Comments,
  evaluations and ideas it writes are yours, in the activity feed and in notifications.
- **Blind evaluation holds.** Until you submit your own evaluation of an idea, the client
  sees no scores, aggregate or other evaluations for it, exactly like the app.
- **Least privilege.** Give an assistant that only reads the **Read with an assistant** preset;
  restrict keys to the projects they need; prefer an expiry. Deleting and moderating
  ideas, project settings, admin pages, your inbox and managing keys always need you
  signed in, so a leaked key can't do them or create another key.
- **Untrusted text.** Ideas, comments, evaluations and proposals are written by people,
  some anonymously through a public form (`via_public_form`). The server tells clients to
  treat that text as information, never as instructions, and never to copy it from one
  project into another. Still review what an agent writes on your behalf, especially if it
  reads more than one project.
- **Hidden text is refused and removed.** Invisible Unicode tag characters (used to hide
  instructions for AI models) are refused in everything people and clients write (422,
  or the tool error `validation_error`), and results carry no invisible characters at all
  (tag characters, zero-width and bidi controls are stripped from every string; emoji,
  accents and right-to-left text are unchanged).
- **Typos don't write.** The read tools ignore arguments they don't know; the four write
  tools refuse them (`validation_error`), so `sumbit: false` can't quietly submit.
- **Limits.** Each key may make 300 requests and 30 changes (create, comment, evaluate,
  suggest) a minute, refused requests included; past that the call answers
  `too_many_attempts`. Ideas waiting for moderation never reach MCP clients, even an
  admin's.
- **Every call is recorded.** Each tool call is in Admin → Audit log (`mcp.call`: the
  tool, allowed or denied, the key; never the arguments), kept for 90 days; what a call
  changed (a submitted evaluation, say) has its own entry, kept for good. A key without
  the `mcp` scope, or past its request budget, is refused at the door, and that is
  recorded at most once a minute per key.
- **Revoking is immediate.** Revoke a key in Settings → API keys (admins: Settings → API keys →
  Everyone’s keys); the client's very next call fails with 401, and each tool call checks the key
  and its owner again when it runs, so a call already on its way when you revoke does
  nothing (the tool error `unauthorized`). Signing out does not stop keys, and
  deactivating a user revokes all of theirs.
- **Lost access shows.** If you lose access to a project a key is restricted to, the key
  stops reaching it at once, and Settings → API keys says "+1 project you can no longer
  open" under the key (admins see that project struck through).
- **Keep the key secret.** It is shown once and stored only as a fingerprint. It starts
  with `sdg_` so secret scanners can spot it (`sdg_[A-Za-z0-9]{12}_[A-Za-z0-9]{40}`); an
  admin can find a leaked key by its first 16 characters in Settings → API keys → Everyone’s keys.

## 5. Soundings' AI agents (kagent)

Phase 6's AI assistance runs kagent agents that use this same server, not as a person but
as **the agent's own service account**. A platform admin registers each agent in Admin
settings → AI agents, which creates its key (shown once, with a Kubernetes Secret holding
`Authorization: Bearer sdg_…` for the agent's `RemoteMCPServer`). Operators:
[operator guide](operator-guide.md#kagent-integration-phase-6) and
[`deploy/kagent/README.md`](../deploy/kagent/README.md).

An agent's key differs from a person's in what it may do (contract-phase6 §3.5, c22, role
matrix §3 rule 9):

- **Only inside a run, and only the run it names.** It works on `/mcp` only (every REST
  route answers 403 `insufficient_scope`), and there only while one of the agent's runs
  is open. **Every call passes that run's id as `run_id`** (the run's message starts
  "Soundings AI run <id>"); the call then reaches only that run's idea and writes only
  that run's result. Without `run_id`, or naming a run that has ended, another kind of
  run or another idea (whether it exists or not), a tool answers `ai_run_not_active`
  before anything is looked up; `list_projects` and `search_ideas` list only the named
  run's project and idea. After a cancel, the deadline or a worker restart the run stays
  over, even while a newer run on the same idea is open. So two runs of one agent can't
  reach each other's ideas, and someone who reaches the agent directly in kagent can't
  use the key for anything else.
- **One write tool per kind of run.** An evaluate run may call `submit_evaluation` (each
  score with a non-empty `comment`, its rationale, and up to 5 `sources`, `{title, url}`
  with http/https URLs), a research run `add_research_note`, a section-draft run
  `propose_proposal_section` for its section only; `create_idea` and `add_comment` are
  refused (`forbidden`). The result is attached to the run.
- **Always blind.** For an agent every idea reads as it does for a pending evaluator, before
  and after it submits (`score_hidden: true`, no aggregate, no other evaluations or their
  comments); it sees its own evaluation only in its evaluate run (`my_evaluation` is null
  in research and draft runs). So nothing an agent writes can carry anyone's scores to a
  pending evaluator, and people's evaluation comments never reach a model provider.
- **Plain text only.** Bidi controls and zero-width characters are removed from an
  agent's note, comment and rationale before they are stored (text that was only those
  is refused); the app shows agent hosts and links isolated from the text around them.
- **Left out of the score.** Its evaluation appears with an AI badge and is left out of the
  aggregate until the idea's owner or an admin includes it; a re-submission that changes a
  score or the recommendation is left out again.
- **What the agent is told.** Each run's A2A message holds the run id, kind, idea key,
  section **key** and the agent's name, plus standing instructions; never a key, a URL or
  idea text (nor a section's title: Phase 8 titles are project admins' text). The agent
  reads the idea through `get_idea` and the section's title and hint through
  `get_proposal` (text labelled untrusted), and must use the MCP server its operator
  configured. A section a project added to its template (`carbon_impact`) is drafted like
  a built-in one; a draft still running when its section is removed gets `unknown_section`
  and ends without a result (`no_result`).
- **Never the research checklist.** An agent reads the checklist and answers in
  `get_idea` like anyone who can see the idea, but nothing lets it answer an item or move
  the idea ("Ask AI to research" writes a research note into the feed; the idea's owner
  turns what is useful into answers).
- **Recorded.** Every call is an `mcp.call` audit entry with the agent's key, and its
  results (the evaluation, note or suggestion) appear in the app with an AI badge.

There is no kagent or model on the build machine: the whole loop is tested with
Soundings' deterministic fake agent (`dev/fake-agent`), which speaks kagent v0.10.2's A2A
layout and really calls these tools with its key. kagent's own controller and a model
have not been run against Soundings yet (operator guide, "What is verified").
