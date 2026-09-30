# ADR 0001: Record architecture decisions

- Status: Accepted · Date: 2026-09-30 · Deciders: lead

## Context

Soundings is built by a lead Claude Code session and several teammates working in
parallel in one working tree (see [../ownership.md](../ownership.md)). Teammates start
with no memory of earlier sessions. A decision that lives only in a chat transcript is
lost at the next phase, and two agents can quietly make opposite choices (for example
one driver in the API and another in the worker).

SPEC.md is the source of truth for *what* to build. It deliberately leaves many *how*
questions open.

## Decision

- We record every decision that constrains more than one owner's code as an ADR in
  `docs/adr/NNNN-short-title.md`, using Context / Decision / Consequences, 20–40 lines.
- Product decisions and "things we chose not to build" go in `docs/decisions.md`, a
  running log; they do not need an ADR unless they change the architecture.
- Only the lead writes or accepts ADRs. Any agent may propose one by messaging the lead
  with the context and the options.
- Accepted ADRs are not edited to change their decision. A new ADR supersedes an old
  one, and the old one's status says so.
- `CLAUDE.md` links to the ADR index so every session loads the pointer.

## Consequences

- New teammates can read ten short files instead of a long transcript.
- Reviewers (code-reviewer, ux-reviewer) can check a change against a written rule.
- Some overhead: a cross-cutting change needs a short write-up before code. That is
  the point; keep ADRs short so the overhead stays small.
