# ADR 0018: Bid evaluation: documents in Postgres, extraction in a worker child, blind sections, checked AI evidence

- Status: Proposed · Date: 2026-10-13 · Extends ADR 0006, 0010, 0012 and 0014
  ([decisions](../decisions.md#phase-10-product-owner-2026-10-13), [contract-phase10](../api/contract-phase10.md))

## Context

The product owner asked to evaluate the bids that come in once an idea has a proposal:
sections of questions, uploaded documents, a must-have checklist so an incomplete bid is
rejected at once, human assessors per section and an AI assessor. Bid documents are the
first files Soundings stores that strangers wrote: Office files can carry macros, ZIP
containers can be bombs, and their text will be read by an LLM. Soundings stays one
image that needs only PostgreSQL and runs air-gapped.

## Decision

1. **A call per idea, with its own relational copy of the project's template** (sections,
   questions, must-haves by id). The project's default is one JSON document per project;
   the copy is rows because assessments, results, assessors and the AI refer to each
   item. The copy locks at the first **person's** submitted assessment; any change clears
   the AI's assessments.
2. **Documents live in PostgreSQL** (`bytea` in `bid_document_contents`, text in
   `bid_document_texts`, metadata apart), like branding images (ADR 0012): no object store,
   one backup, deletion by cascade. Bounded at 25 MiB a file, 30 a bid, 500 MiB a call.
   Read in 1 MiB chunks for download; lists never touch the bytes.
3. **Raw-body upload** on one route with its **own body limit** (25 MiB, counted while
   streaming, so a lying `Content-Length` or a chunked body stops at the limit) while the
   1 MiB limit stays everywhere else; the name and must-have travel as query parameters.
   `python-multipart` is installed (through `mcp`), but a raw body needs no parser, no
   spooled temporary files (the API runs read-only with a small `/tmp`) and one bound.
   At most two uploads at once per API process (503 `upload_busy`).
4. **Type by content, not name**: magic bytes and, for ZIP containers, the parts inside;
   PDF, DOCX, XLSX, PPTX, ODT, ODS, TXT, CSV, PNG, JPEG only; macro-enabled or active
   Office files, OpenDocument scripts and encrypted files refused (415). Downloads are
   always attachments with `nosniff`, a sandboxing CSP and `no-store`; the SPA never
   renders a document, only its extracted text, as text.
5. **Text extraction in the worker, in a child process** (30 s, a memory cap, 2 million
   characters), never in the API: `pypdf` (BSD-3-Clause, pure Python, promoted from a dev
   dependency) for PDF; `zipfile` and `ElementTree` for OOXML and ODF, refusing a
   `DOCTYPE` and capping entries, sizes and the compression ratio; no `defusedxml` or
   `lxml` (not needed once `DOCTYPE` is refused). No OCR.
6. **No antivirus scanning in this phase**: files are never executed, rendered or opened
   on the server except by the extractor child; the operator guide says how to add a
   scanner (an ICAP or ClamAV sidecar on the upload path) where policy requires one.
7. **Blind per (bid, section)** (role matrix 3a): an assessor sees nobody's scores for a
   bid and section until they submit theirs, and never totals or ranks; **prices** only
   for call managers and the price section's assessors. Rules in the one policy module
   (ADR 0010), a +Asr overlay from `bid_section_assessors`; a guest researcher gets 404
   for all of it (table L, deny by default).
8. **The AI assessor is an AI run** (ADR 0014): purpose and kind `assess_bid`, one run per
   bid, three MCP tools bound to the run's bid (c22), never other bids, people's scores or
   the price. **Every quote is checked** against the extracted text (whitespace
   normalised); a quote that isn't there is stored and shown "not found". Its scores stay
   out of the totals until a call manager includes them; findings never change a result.
9. **Scoring with exact fractions**, rounded half up only for display (0-5 to 2 decimals,
   0-100 to 1); ranks by the rounded total, ties share a rank and are left to a person.

## Consequences

- Database size grows with documents (up to 500 MiB a call): backups and the bundled
  volume need sizing; the operator guide says so, and deleting the idea deletes them.
- Bidders' documents may hold personal data; they live as long as the call.
- Document text is untrusted everywhere it flows: plain text in the SPA, evidence in the
  agent's instructions, quotes verified rather than trusted.
- One more worker queue and child process; a failed extraction never refuses a document.
- Assigning assessors, uploads and decisions are session only: a leaked key can read and
  score, never open bids to someone, plant a file or reject a bid.
