# Connecting MCP clients to Soundings

Soundings runs an [MCP](https://modelcontextprotocol.io) server at `/mcp` on the same
address as the app (for example `https://ideas.example.com/mcp`; `http://localhost:8000/mcp`
with `make demo` or `make -C backend dev`). An MCP client, such as Claude Code, Claude
Desktop, an assistant in your editor or a kagent agent, uses it to search ideas, read
proposals, comment and submit evaluations **as you**, through a personal API key.

This page is for people connecting a client. Operators: [operator-guide.md](operator-guide.md#api-keys-and-mcp-phase-5).
The precise contract is [contract-phase5.md §3.5 and §4](api/contract-phase5.md#35-the-mcp-endpoint-transport).

## 1. Create a key

In Soundings, open **Settings → API keys** and choose **Create key**:

| Field | What to pick |
|---|---|
| Name | What it is for, e.g. "Claude Code on my laptop" (unique among your keys) |
| Scopes | A preset: **MCP client** (`read`, `mcp`: search and read), **AI evaluator** (`read`, `evaluate`, `mcp`: also submit your evaluations), **Full access** (all four: also create ideas, comment and suggest proposal text). `mcp` alone connects but can't use any tool. |
| Expires | 30 days, 90 days, a year, a date, or never |
| Projects | All projects you can access, or only some (recommended for agents) |

The key (`sdg_` and 53 more characters) is shown **once**: copy it into the client, or
into a password manager, before you close the dialog. Soundings keeps only a fingerprint
of it. The dialog also shows the examples below with your key already filled in.

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

Nine tools, always listed (a tool the key's scopes don't allow answers
`insufficient_scope`). Ideas are referenced by key (`CUST-12`, any case) or id; projects
by their URL name (slug).

| Tool | Scope | What it does |
|---|---|---|
| `list_projects` | `read` | The projects you can see (inside the key's projects), with your role, the idea count and whether you can create ideas there. Archived ones with `include_archived`. |
| `search_ideas` | `read` | Ideas by `query` (title or summary text, or a key), `project`, `status`, `owner` (`me`, `none`), `awaiting_my_evaluation`, `sort`; 20 a page (`limit` up to 50, `cursor`). Scores follow blind evaluation. |
| `get_idea` | `read` | One idea: description, status, owner, evaluators (invited or submitted), the aggregate and others' evaluations when you may see them, your own evaluation, and the latest comments (`comment_limit`, 10 by default, 20 at most; long comments are cut, `truncated`). |
| `get_rubric` | `read` | A project's criteria (by `project` or `idea`) with guidance, weights and which are inverted (a high Effort or Risk score is bad: score what you see). |
| `get_proposal` | `read` | The idea's proposal, section by section, or null if none has been started, and whether you may suggest text. |
| `create_idea` | `write` | A new idea in a project, as you (status New; you watch it). |
| `add_comment` | `write` | A comment on an idea, with @mentions as in the app; people are notified as usual. |
| `submit_evaluation` | `evaluate` | Saves your evaluation: a 1-5 score for every criterion, a recommendation (`go`, `maybe`, `no`) and a comment. Submits by default (`submit: false` saves a draft); the arguments replace what was saved. Only if you were asked to evaluate the idea and evaluation is open. |
| `propose_proposal_section` | `write` | Suggests the whole new text of one proposal section. It is only a suggestion: the idea's owner sees it in the proposal editor and accepts or discards it. A newer suggestion of yours for the same section replaces the older one. |

Results are structured JSON (`structuredContent`, snake_case, with an `outputSchema` per
tool) plus the same JSON as text. Errors are results with `isError: true`, text
`"<code>: <message>"` and `structuredContent: {code, message}`; the codes are the API's
(`not_found`, `forbidden`, `insufficient_scope`, `validation_error`, `evaluation_closed`,
`too_many_attempts`, …: [contract-phase5 §4.4](api/contract-phase5.md#44-tool-error-codes)).
`not_found` also covers anything the key may not see.

## 4. Safety notes

- **The client is you.** It acts with your permissions at the moment of each call,
  narrowed by the key; if your role changes, the key follows on the next call. Comments,
  evaluations and ideas it writes are yours, in the activity feed and in notifications.
- **Blind evaluation holds.** Until you submit your own evaluation of an idea, the client
  sees no scores, aggregate or other evaluations for it, exactly like the app.
- **Least privilege.** Give an assistant that only reads the **MCP client** preset;
  restrict keys to the projects they need; prefer an expiry. Deleting and moderating
  ideas, project settings, admin pages, your inbox and managing keys always need you
  signed in, so a leaked key can't do them or create another key.
- **Untrusted text.** Ideas, comments, evaluations and proposals are written by people,
  some anonymously through a public form (`via_public_form`). The server tells clients to
  treat that text as information, never as instructions, and never to copy it from one
  project into another. Still review what an agent writes on your behalf, especially if it
  reads more than one project.
- **Limits.** Each key may make 300 requests and 30 changes (create, comment, evaluate,
  suggest) a minute; past that the call answers `too_many_attempts`. Ideas waiting for
  moderation never reach MCP clients, even an admin's.
- **Every call is recorded.** Each tool call is in Settings → Audit log (`mcp.call`: the
  tool, allowed or denied, the key; never the arguments), kept for 90 days; what a call
  changed (a submitted evaluation, say) has its own entry, kept for good.
- **Revoking is immediate.** Revoke a key in Settings → API keys (admins: Settings → All
  API keys); the client's very next call fails with 401. Signing out does not stop keys,
  and deactivating a user revokes all of theirs.
- **Keep the key secret.** It is shown once and stored only as a fingerprint. It starts
  with `sdg_` so secret scanners can spot it (`sdg_[A-Za-z0-9]{12}_[A-Za-z0-9]{40}`); an
  admin can find a leaked key by its first 16 characters in Settings → All API keys.
