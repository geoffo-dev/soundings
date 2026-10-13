# ADR 0018: Bid evaluation: documents in Postgres, extraction in a worker child, blind sections, checked AI evidence

- Status: Proposed (amended by the contract review, 2026-10-13) · Date: 2026-10-13 ·
  Extends ADR 0006, 0010, 0012 and 0014
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
2. **Documents live in PostgreSQL** (`bytea` in `bid_document_contents`, `STORAGE
   EXTERNAL` for cheap range reads; text in `bid_document_texts`, metadata apart), like
   branding images (ADR 0012): no object store, one backup, deletion by cascade. Bounded at
   25 MiB a file, 30 a bid, 500 MiB a call and 5 GiB a project, **extracted text counted**.
   Read in 1 MiB chunks for download; lists never touch the bytes.
3. **Raw-body upload** on one route with its **own body limit** (25 MiB, counted while
   streaming, so a lying `Content-Length` or a chunked body stops at the limit) while the
   1 MiB limit stays everywhere else; the name, must-have and pricing mark travel as query
   parameters. `python-multipart` is installed (through `mcp`), but a raw body needs no
   parser, no spooled temporary files (the API runs read-only with a small `/tmp`) and one
   bound. Authentication, the 404s and 403s and an upload slot (two per API process, 503
   `upload_busy`) come **before** the body is read; the body is read into one buffer
   within 120 s with **no transaction open**.
4. **Type by content, not name, and bounded**: magic bytes for PDF, PNG and JPEG (no PDF
   is parsed in the API); for ZIP containers the end record's entry count first (more than
   2,000: refused), then the central directory's **names** only and two bounded reads
   (`[Content_Types].xml` up to 256 KiB, `mimetype` up to 64 bytes) checked by substring,
   never parsed, in a thread; text by decoding. PDF, DOCX, XLSX, PPTX, ODT, ODS, TXT, CSV,
   PNG, JPEG only; macro-enabled Office files, embedded OLE packages and nested macro
   files (by name), OpenDocument scripts and encrypted Office files refused (415). The
   request's `Content-Type` is ignored. Downloads are always attachments with `nosniff`, a
   sandboxing CSP and `no-store`; the SPA never renders a document, only its extracted
   text, as text, and warns before downloading one the extractor flagged
   (`active_content`: PDF scripts, launch actions or attached files; remote templates,
   external links, DDE).
5. **Text extraction in the worker, in a child process**, never in the API: one at a time
   per worker; 30 s, a 512 MiB address-space cap in a 1 GiB worker, 2 million characters;
   an allow-listed environment (the worker's database URL, secret key and SMTP
   credentials stay out), bytes on stdin and bounded output on stdout, three crashes at
   most per document. `pypdf` (BSD-3-Clause, pure Python, promoted from a dev dependency)
   for PDF; `zipfile` and `ElementTree.iterparse` for OOXML and ODF, refusing a `DOCTYPE`,
   with 2,000 entries, 50 MiB a part and 200 MiB in all counted as they stream, a ratio of
   100 and no nested archives; no `defusedxml` or `lxml` (not needed once `DOCTYPE` is
   refused). No OCR. The child stores the text **without NULs and hidden characters**
   (`app.mcp.text.visible_text`), so people, agents and quote checks read the same text.
6. **No antivirus scanning in this phase**: files are never executed, rendered or opened
   on the server except by the extractor child; the operator guide says how to add a
   scanner (an ICAP or ClamAV sidecar on the upload path) where policy requires one.
7. **Blind per (bid, section)** (role matrix 3a): an assessor sees nobody's scores for a
   bid and section until they submit theirs, and never totals or ranks; a call manager who
   owes any assessment sees **no ranks at all** (the gaps would place the hidden bid); a
   rejection never ends blindness; nobody steps out of a section they owe
   (`cannot_remove_self`) and submitted work is never deleted (`assessor_has_submitted`).
   **Prices and pricing documents** only for call managers and the price section's
   assessors (a document is pricing when marked so or linked to a pricing must-have, like
   the default "Pricing schedule"). Rules in the one policy module (ADR 0010), a +Asr
   overlay from `bid_section_assessors` checked live (c28, never through a guest
   researcher's column R); a guest researcher gets 404 for all of it (table L, deny by
   default).
8. **The AI assessor is an AI run** (ADR 0014): purpose and kind `assess_bid`, one run per
   bid, three MCP tools bound to the run's bid (c22), never other bids, people's scores,
   the price or pricing documents. A call may name one AI assessor, which runs **once
   automatically per bid** when the bid's documents are read (not counted toward anyone's
   hourly limit); later runs are people's requests. **Every quote is checked** against the
   extracted text (whitespace normalised, each document once, off the event loop); a quote
   that isn't there is stored and shown "not found". Its scores stay out of the totals
   until a call manager includes them; findings never change a result. Rejecting, a
   template change, a pricing mark, the award and cancelling cancel its active runs.
9. **Scoring with exact fractions**, rounded half up only for display (0-5 to 2 decimals,
   0-100 to 1), for the bids that **are** scored by their facts (not rejected, every
   must-have met), before and after the award alike; ranks by the rounded total, ties
   share a rank and are left to a person.
10. **One call per row family in the schema**: every row that names two of a call's rows
    (a question and its section, an assessor and their section, a must-have result, a
    document and its bid and must-have, an assessment and its bid and assignment, an
    assess run and its bid and idea) does it through a composite foreign key with the
    call's id, so the database refuses a row that mixes two calls.

## Consequences

- Database size grows with documents (up to 500 MiB a call): backups and the bundled
  volume need sizing; the operator guide says so, and deleting the idea deletes them.
- Bidders' documents may hold personal data; they live as long as the call.
- Document text is untrusted everywhere it flows: plain text in the SPA, evidence in the
  agent's instructions, quotes verified rather than trusted.
- One more worker queue and child process; a failed extraction never refuses a document.
- Assigning assessors, documents (uploads, the pricing mark, deleting) and decisions are
  session only: a leaked key can read and score, never open bids or a pricing document to
  someone, plant a file or reject a bid.
- The worker container needs 1 GiB (the extraction child's 512 MiB plus the worker), and
  the ingress must allow the upload route's 25 MiB body (and 120 s) without raising the
  limit for the rest of the API.
