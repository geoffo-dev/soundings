"""Bid evaluation (Phase 10, product owner 2026-10-13; contract-phase10, ADR 0018): the
project's default bid evaluation template (Project settings -> Bids) and an idea's call
for bids (the idea page's Bids tab): its template copy, lifecycle and assessors, the bids
the team enters with their documents and must-haves, the section assessors' assessments,
the comparison, the AI assessor, the award and the evaluation report.

Rules (role matrix table M): ``bid.view_call`` (that a call exists: everyone who can view
the idea but a guest researcher), ``bid.manage`` (call managers: the idea's owner, project
admins, platform admins), ``bid.upload_document`` and ``bid.decide`` (call managers,
**session only**), ``bid.view_bids`` (call managers and section assessors),
``bid.view_price`` (call managers and the price section's assessors), ``bid.assess`` (a
section's assessors), ``bid.view_scores`` (call managers; blind for their own pending
assessments), ``bid.view_section_scores`` (a section's assessors after submitting it, and
call managers), ``ai.assess_bid`` (call managers, c10), ``project.edit_bid_template``
(project and platform admins, session only). Order of checks: 401 -> 404 (the idea, the
call, the bid, a section or document of another call; a rejected bid for an assessor who
isn't a call manager) -> 403 -> 422 -> 409 (``project_archived``, ``idea_closed``, the
call's state) -> 413 / 415 for uploads.

Every route here answers 501 until backend builds it (``tests/test_contract_routes.py``
``STUBS``).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Request, status
from fastapi.responses import Response

from app.api.v1.ideas import IdeaParam
from app.api.v1.principal import PrincipalDep
from app.api.v1.projects import ProjectSlug
from app.api.v1.responses import binary, binary_body, problems
from app.db import SessionDep
from app.errors import NotImplementedProblem
from app.schemas.ai import AiRun, AiRunRequest
from app.schemas.bids import (
    BID_DOCUMENT_TYPES,
    BID_TEXT_PAGE_CHARS,
    AiRunBatch,
    BidAiAssessment,
    BidAiAssessmentList,
    BidAiInclusionUpdate,
    BidAssessorsUpdate,
    BidAwardIn,
    BidCallCreate,
    BidCallStatusChange,
    BidCallTemplate,
    BidCallTemplateIn,
    BidCallUpdate,
    BidCallView,
    BidComparison,
    BidDetail,
    BidDocument,
    BidDocumentFilename,
    BidDocumentText,
    BidDocumentUpdate,
    BidIn,
    BidList,
    BidMustHaveState,
    BidRejectionIn,
    BidSectionAssessments,
    BidTemplate,
    BidTemplateIn,
    MustHaveDecisionIn,
    MyBidAssessment,
    MyBidAssessmentIn,
)
from app.schemas.bids import Bid as BidOut

router = APIRouter(tags=["bids"])

BidId = Annotated[UUID, Path(description="A bid of the idea's call.")]
DocumentId = Annotated[UUID, Path(description="A document of that bid.")]
SectionId = Annotated[UUID, Path(description="A section of the call's template.")]
MustHaveId = Annotated[UUID, Path(description="A must-have of the call's template.")]
AiAssessmentId = Annotated[UUID, Path(description="An AI assessment of that bid.")]

_CALL = "/ideas/{idea}/bid-call"
_BID = _CALL + "/bids/{bid_id}"
_CALL_STATE = (
    " 409 project_archived, idea_closed (c5), bid_call_finished (the call is awarded or "
    "cancelled: read-only)."
)
_DOWNLOAD_HEADERS = {
    "Content-Disposition": (
        "attachment; filename=\"<safe ASCII name>\"; filename*=UTF-8''<the stored name>"
    ),
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Cache-Control": "private, no-store",
}
_REPORT_HEADERS = {
    "Content-Disposition": 'attachment; filename="<KEY>-bid-evaluation.<ext>" (e.g. TOOLS-3).',
}
_UPLOAD = binary_body(
    *sorted({info.media_type.split(";")[0] for info in BID_DOCUMENT_TYPES.values()}),
    "application/octet-stream",
    description=(
        "The file itself as the body (no multipart, no JSON), at most 25 MiB. Its type is "
        "decided from its bytes: PDF, DOCX, XLSX, PPTX, ODT, ODS, plain text, CSV, PNG or "
        "JPEG; macro-enabled Office files and anything else are refused. Content-Type: the "
        "file's own type or application/octet-stream (a different allowed type than the "
        "bytes are: 415 document_type_mismatch)."
    ),
)


# --- The project's default template (Project settings -> Bids) -------------------------
@router.get(
    "/projects/{slug}/bid-template",
    operation_id="get_bid_template",
    summary="Project settings: the bid evaluation template",
    description=(
        "project.view: the project's default bid evaluation template (scale anchors, weighted "
        "sections of questions, must-haves). Calls copy it when they start. Holds no bids."
    ),
    responses=problems(401, 404),
)
async def get_bid_template(
    principal: PrincipalDep, session: SessionDep, slug: ProjectSlug
) -> BidTemplate:
    raise NotImplementedProblem


@router.put(
    "/projects/{slug}/bid-template",
    operation_id="replace_bid_template",
    summary="Replace the bid evaluation template",
    description=(
        "project.edit_bid_template (project and platform admins, session only): the complete "
        "template; last write wins. Existing calls keep their own copy. Audited "
        "project.bid_template_replace. 422 validation_error (1-8 sections whose weights sum "
        "to 100, 1-15 questions each with a score question, at most one price question, "
        "0-20 must-haves, unique titles). Allowed in an archived project (settings, like the "
        "proposal template)."
    ),
    responses=problems(401, 403, 404, 422),
)
async def replace_bid_template(
    principal: PrincipalDep, session: SessionDep, slug: ProjectSlug, body: BidTemplateIn
) -> BidTemplate:
    raise NotImplementedProblem


# --- The call ----------------------------------------------------------------------------
@router.get(
    _CALL,
    operation_id="get_bid_call",
    summary="The Bids tab",
    description=(
        "bid.view_call: the call's summary (title, status, deadline, number of bids) for "
        "everyone who may see it, the whole call for call managers and section assessors "
        "(bid.view_bids), the agents that may assess and what you may do. Null summary and "
        "call when the idea has none. A guest researcher: 404. No score data."
    ),
    responses=problems(401, 404),
)
async def get_bid_call(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> BidCallView:
    raise NotImplementedProblem


@router.post(
    _CALL,
    operation_id="create_bid_call",
    status_code=status.HTTP_201_CREATED,
    summary="Start a call for bids",
    description=(
        "bid.manage (c27): a draft call with a copy of the project's bid evaluation template. "
        "The idea must be in Proposal with a proposal (409 bid_call_not_available) and have "
        "no call yet (409 bid_call_exists). Emits bid_call_changed (started); audited "
        "bid_call.create." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def create_bid_call(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: BidCallCreate
) -> BidCallView:
    raise NotImplementedProblem


@router.put(
    _CALL,
    operation_id="update_bid_call",
    summary="Change the call's settings",
    description=(
        "bid.manage: title, description, currency (until the template is locked: 409 "
        "bid_call_template_locked), deadline (an open call keeps one: 409 "
        "bid_call_deadline_required) and the assessment due date; the complete new state, "
        "last write wins. Audited bid_call.update (the fields changed, never their values)."
        + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def update_bid_call(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: BidCallUpdate
) -> BidCallView:
    raise NotImplementedProblem


@router.delete(
    _CALL,
    operation_id="delete_bid_call",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the call",
    description=(
        "bid.decide (session only): a draft or cancelled call, with its bids, documents and "
        "assessments (409 bid_call_active otherwise: cancel it first). Frees the idea for a "
        "new call. Audited bid_call.delete. 409 project_archived."
    ),
    responses=problems(401, 403, 404, 409),
)
async def delete_bid_call(principal: PrincipalDep, session: SessionDep, idea: IdeaParam) -> None:
    raise NotImplementedProblem


@router.post(
    _CALL + "/status",
    operation_id="change_bid_call_status",
    summary="Open, assess or cancel the call",
    description=(
        "bid.manage (open, assessing; cancelling is bid.decide, session only): draft -> open "
        "(needs a deadline: 409 bid_call_deadline_required), open -> assessing (no new bids), "
        "assessing -> open (only while no assessment is submitted: 409 "
        "assessments_submitted), draft / open / assessing -> cancelled (an optional reason). "
        "Any other move: 409 invalid_bid_call_transition. Emits bid_call_changed; audited "
        "bid_call.status_change." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def change_bid_call_status(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: BidCallStatusChange
) -> BidCallView:
    raise NotImplementedProblem


@router.put(
    _CALL + "/template",
    operation_id="replace_bid_call_template",
    summary="Edit the call's evaluation template",
    description=(
        "bid.manage: the call's own template, complete (items keep their ids; left out = "
        "deleted with their assessor assignments, results and document links; new must-haves "
        "get a result for every bid). Until the first human assessment is submitted (409 "
        "bid_call_template_locked). Any change clears the call's AI assessments. Audited "
        "bid_call.template_replace. 422 validation_error, unknown_template_item." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def replace_bid_call_template(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: BidCallTemplateIn
) -> BidCallTemplate:
    raise NotImplementedProblem


@router.put(
    _CALL + "/assessors",
    operation_id="set_bid_assessors",
    summary="Assign the section assessors",
    description=(
        "bid.manage, **session only** (an assignment opens the bids and their documents to a "
        "person): every section's assessors and the assessment due date, the complete new "
        "state. Assessors must be active people who can view the idea (in a private project: "
        "a role there; c28, else 422 assessor_not_eligible), never an AI agent or the "
        'break-glass account. People added get "Asked to assess bids"; people removed from a '
        "section lose their assessments of it. Audited bid_call.assessors_change. 422 "
        "unknown_section (a section of another call or one left out)." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def set_bid_assessors(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: BidAssessorsUpdate
) -> BidCallView:
    raise NotImplementedProblem


@router.get(
    _CALL + "/comparison",
    operation_id="get_bid_comparison",
    summary="Compare the bids",
    description=(
        "bid.view_scores (call managers): every bid with its section scores (0-100), total "
        "(0-100), rank, price score, disagreement and progress; qualified bids ranked first. "
        "What you owe an assessment for yourself is hidden (blind: role matrix section 3a)."
    ),
    responses=problems(401, 403, 404),
)
async def get_bid_comparison(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> BidComparison:
    raise NotImplementedProblem


@router.post(
    _CALL + "/ai-assessments",
    operation_id="request_ai_bid_assessments",
    summary="Assess all bids with AI",
    description=(
        "ai.assess_bid (c5, c10): one assess run per bid that isn't rejected, for the agent "
        "named (active runs are returned as they are). The call must be open or being "
        "assessed (409 bid_call_not_assessable). Each new run counts toward your 20 AI "
        "requests an hour; beyond: 429 too_many_attempts and nothing starts. Audited "
        "ai_run.request per run. 409 ai_unavailable." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422, 429),
)
async def request_ai_bid_assessments(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: AiRunRequest
) -> AiRunBatch:
    raise NotImplementedProblem


@router.post(
    _CALL + "/award",
    operation_id="award_bid_call",
    summary="Award the call",
    description=(
        "bid.decide (session only), while the call is being assessed (409 "
        "bid_call_not_assessing): one qualified bid is awarded (409 bid_not_qualified; a "
        "rejected one: 409 bid_rejected), every other bid that isn't rejected becomes "
        "unsuccessful, and the call is read-only. Outstanding assessments don't block it "
        "(the SPA warns). Emits bid_call_changed (awarded); audited bid_call.award." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def award_bid_call(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: BidAwardIn
) -> BidCallView:
    raise NotImplementedProblem


@router.get(
    _CALL + "/report/markdown",
    operation_id="export_bid_report_markdown",
    response_class=Response,
    summary="The evaluation report (Markdown)",
    description=(
        "bid.view_scores (call managers only): the ranking, each bid's section scores and "
        "total, must-have results, rejected bids with their reasons, the assessors per "
        "section, whether the AI was included, and the award. What you owe an assessment "
        "for is left out. Shares the export limit with proposals (429 too_many_attempts)."
    ),
    responses={
        **binary(200, "The report as Markdown (UTF-8).", "text/markdown", headers=_REPORT_HEADERS),
        **problems(401, 403, 404, 429),
    },
)
async def export_bid_report_markdown(
    request: Request, principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> Response:
    raise NotImplementedProblem


@router.get(
    _CALL + "/report/pdf",
    operation_id="export_bid_report_pdf",
    response_class=Response,
    summary="The evaluation report (PDF)",
    description=(
        "bid.view_scores (call managers only): the Markdown report's content as a branded "
        "PDF from the PDF child process (as proposal exports). 429 too_many_attempts; 503 "
        "export_busy."
    ),
    responses={
        **binary(200, "The report as a PDF.", "application/pdf", headers=_REPORT_HEADERS),
        **problems(401, 403, 404, 429, 503),
    },
)
async def export_bid_report_pdf(
    request: Request, principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> Response:
    raise NotImplementedProblem


# --- Bids ----------------------------------------------------------------------------------
@router.get(
    _CALL + "/bids",
    operation_id="list_bids",
    summary="The call's bids",
    description=(
        "bid.view_bids (call managers and section assessors): in the order received. Section "
        "assessors don't get rejected bids, contact details, notes or rejection reasons; "
        "prices follow bid.view_price. Not paged (at most 50)."
    ),
    responses=problems(401, 403, 404),
)
async def list_bids(principal: PrincipalDep, session: SessionDep, idea: IdeaParam) -> BidList:
    raise NotImplementedProblem


@router.post(
    _CALL + "/bids",
    operation_id="create_bid",
    status_code=status.HTTP_201_CREATED,
    summary="Enter a bid",
    description=(
        "bid.manage, while the call is open (409 bid_call_not_open): the bidder, optional "
        "contact, when it was received (late after the deadline, not refused), the price (422 "
        "price_not_asked without a price question) and notes. Its must-haves start missing or "
        "unchecked. 409 too_many_bids (50). Audited bid.create." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def create_bid(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: BidIn
) -> BidOut:
    raise NotImplementedProblem


@router.get(
    _BID,
    operation_id="get_bid",
    summary="A bid",
    description=(
        "bid.view_bids: the bid with its documents, must-have results (and the AI's "
        "suggestions), your sections and what you may do. A rejected bid is 404 for a section "
        "assessor who isn't a call manager. No score data."
    ),
    responses=problems(401, 403, 404),
)
async def get_bid(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, bid_id: BidId
) -> BidDetail:
    raise NotImplementedProblem


@router.put(
    _BID,
    operation_id="update_bid",
    summary="Edit a bid",
    description=(
        "bid.manage: the complete new state (received_at required). Before the award. A "
        "changed price changes every qualified bid's price score. Audited bid.update (the "
        "fields changed, never their values)." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def update_bid(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, bid_id: BidId, body: BidIn
) -> BidOut:
    raise NotImplementedProblem


@router.delete(
    _BID,
    operation_id="delete_bid",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a bid",
    description=(
        "bid.decide (session only), while the call is a draft or open (409 bid_call_not_open; "
        "nobody has assessed it then): the bid and its documents. Audited bid.delete." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409),
)
async def delete_bid(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, bid_id: BidId
) -> None:
    raise NotImplementedProblem


@router.put(
    _BID + "/rejection",
    operation_id="reject_bid",
    summary="Reject a bid",
    description=(
        "bid.decide (session only): one click and a reason, any time before the award (a new "
        "reason replaces the old one). The bid leaves the assessors' queues, the totals, the "
        "price formula and the ranking. Audited bid.reject." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def reject_bid(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    bid_id: BidId,
    body: BidRejectionIn,
) -> BidOut:
    raise NotImplementedProblem


@router.delete(
    _BID + "/rejection",
    operation_id="reinstate_bid",
    summary="Reinstate a bid",
    description=(
        "bid.decide (session only): undo a rejection before the award (idempotent); the bid "
        "is received or qualified again by its must-haves, its assessments count again. "
        "Audited bid.reinstate." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409),
)
async def reinstate_bid(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, bid_id: BidId
) -> BidOut:
    raise NotImplementedProblem


@router.put(
    _BID + "/must-haves/{must_have_id}",
    operation_id="decide_must_have",
    summary="Decide a must-have",
    description=(
        "bid.manage: met or not met (with a note), or clear the decision. A document "
        "must-have without a linked file can't be met (409 document_missing). The bid "
        "becomes qualified when every must-have is met. Audited bid.must_have_decide." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def decide_must_have(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    bid_id: BidId,
    must_have_id: MustHaveId,
    body: MustHaveDecisionIn,
) -> BidMustHaveState:
    raise NotImplementedProblem


# --- Documents -------------------------------------------------------------------------------
@router.post(
    _BID + "/documents",
    operation_id="upload_bid_document",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a bid document",
    description=(
        "bid.upload_document (session only), before the award: the raw file as the body (this "
        "route alone takes up to 25 MiB: 413 content_too_large beyond, also for a body longer "
        "than its Content-Length says or a chunked one). Allowed by its bytes: 415 "
        "unsupported_document_type (anything else, also an empty or encrypted file), "
        "macro_document (VBA or ActiveX in an Office file, scripts in an OpenDocument file), "
        "document_type_mismatch (Content-Type is another allowed type). 409 "
        "too_many_documents (30 per bid), call_storage_full (500 MiB per call), "
        "duplicate_document (the same file on this bid). 422 invalid_must_have "
        "(must_have_id names a confirmation or another call's). 503 upload_busy (with "
        "Retry-After). Text is extracted afterwards by the worker (extraction.state pending). "
        "Audited bid_document.upload." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 413, 415, 422, 503),
    openapi_extra=_UPLOAD,
)
async def upload_bid_document(
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    bid_id: BidId,
    filename: Annotated[
        BidDocumentFilename, Query(description="The file's name (shown and used on download).")
    ],
    must_have_id: Annotated[
        UUID | None, Query(description="A required-document must-have it satisfies.")
    ] = None,
) -> BidDocument:
    raise NotImplementedProblem


@router.put(
    _BID + "/documents/{document_id}",
    operation_id="update_bid_document",
    summary="Link a document to a must-have",
    description=(
        "bid.manage: link it to a required-document must-have (which then counts as present: "
        "met unless a person decided otherwise) or unlink it (null; the must-have is missing "
        "again when no other file is linked). 422 invalid_must_have." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def update_bid_document(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    bid_id: BidId,
    document_id: DocumentId,
    body: BidDocumentUpdate,
) -> BidDocument:
    raise NotImplementedProblem


@router.delete(
    _BID + "/documents/{document_id}",
    operation_id="delete_bid_document",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a bid document",
    description=(
        "bid.upload_document (session only), before the award: the file, its text and its "
        "link (a must-have left without a file is missing again). Audited "
        "bid_document.delete." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409),
)
async def delete_bid_document(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    bid_id: BidId,
    document_id: DocumentId,
) -> None:
    raise NotImplementedProblem


@router.get(
    _BID + "/documents/{document_id}/content",
    operation_id="download_bid_document",
    response_class=Response,
    summary="Download a bid document",
    description=(
        "bid.view_bids: the file as stored, always as an attachment (never shown inline), "
        "with its type's media type, nosniff, a sandboxing CSP and Cache-Control private, "
        "no-store; read from the database in chunks. Not audited (a read)."
    ),
    responses={
        **binary(
            200,
            "The document.",
            *sorted({info.media_type for info in BID_DOCUMENT_TYPES.values()}),
            headers=_DOWNLOAD_HEADERS,
        ),
        **problems(401, 403, 404),
    },
)
async def download_bid_document(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    bid_id: BidId,
    document_id: DocumentId,
) -> Response:
    raise NotImplementedProblem


@router.get(
    _BID + "/documents/{document_id}/text",
    operation_id="get_bid_document_text",
    summary="A bid document's text",
    description=(
        f"bid.view_bids: one page ({BID_TEXT_PAGE_CHARS:,} characters) of the text the worker "
        "extracted (plain text written by the bidder: show it as text, never as HTML). Empty "
        "while pending, for images and when extraction failed. 404 for a page past the last."
    ),
    responses=problems(401, 403, 404),
)
async def get_bid_document_text(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    bid_id: BidId,
    document_id: DocumentId,
    page: Annotated[int, Query(ge=1, le=100, description="1-based.")] = 1,
) -> BidDocumentText:
    raise NotImplementedProblem


# --- Assessments ---------------------------------------------------------------------------
@router.get(
    _BID + "/sections/{section_id}/assessment",
    operation_id="get_my_bid_assessment",
    summary="Your assessment of a section",
    description=(
        "bid.assess (you assess the section): your draft or submitted answers (state invited "
        "when nothing is saved). 403 for a section you don't assess."
    ),
    responses=problems(401, 403, 404),
)
async def get_my_bid_assessment(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    bid_id: BidId,
    section_id: SectionId,
) -> MyBidAssessment:
    raise NotImplementedProblem


@router.put(
    _BID + "/sections/{section_id}/assessment",
    operation_id="save_my_bid_assessment",
    summary="Save or submit your assessment",
    description=(
        "bid.assess, while the call is being assessed (409 bid_call_not_assessing) and the "
        "bid isn't rejected (409 bid_rejected): save a draft, or submit (every score question "
        "scored 0-5: 422 assessment_incomplete); editable after submitting until the award. "
        "422 unknown_question, not_assessable (the price question). The first submission is "
        "audited bid_assessment.submit and locks the template. An API key needs evaluate."
        + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def save_my_bid_assessment(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    bid_id: BidId,
    section_id: SectionId,
    body: MyBidAssessmentIn,
) -> MyBidAssessment:
    raise NotImplementedProblem


@router.get(
    _BID + "/sections/{section_id}/assessments",
    operation_id="list_bid_section_assessments",
    summary="A section's assessments",
    description=(
        "bid.view_section_scores: the submitted assessments of the section for this bid, the "
        "AI's scores for it, per-question statistics and the section score. Hidden (hidden: "
        "true, nothing else) while you owe this assessment yourself; an assessor of another "
        "section: 403."
    ),
    responses=problems(401, 403, 404),
)
async def list_bid_section_assessments(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    bid_id: BidId,
    section_id: SectionId,
) -> BidSectionAssessments:
    raise NotImplementedProblem


# --- The AI assessor -----------------------------------------------------------------------
@router.post(
    _BID + "/ai-assessment",
    operation_id="request_ai_bid_assessment",
    status_code=status.HTTP_201_CREATED,
    summary="Ask AI to assess a bid",
    description=(
        "ai.assess_bid (c5, c10): an assess run for this bid (201), or the active one (200). "
        "The call open or being assessed (409 bid_call_not_assessable), the bid not rejected "
        "(409 bid_rejected). Counts toward your 20 AI requests an hour (429). Audited "
        "ai_run.request. 409 ai_unavailable." + _CALL_STATE
    ),
    responses={
        200: {
            "description": (
                "An assess run of this bid by this agent is already active (queued or running): "
                "that run, unchanged (idempotent)."
            ),
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AiRun"}}},
        },
        **problems(401, 403, 404, 409, 422, 429),
    },
)
async def request_ai_bid_assessment(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    bid_id: BidId,
    body: AiRunRequest,
) -> AiRun:
    raise NotImplementedProblem


@router.get(
    _BID + "/ai-assessments",
    operation_id="list_bid_ai_assessments",
    summary="The AI's assessments of a bid",
    description=(
        "bid.view_scores (call managers): each agent's scores with rationale and quoted "
        "evidence (each quote checked against the document's text), its must-have findings, "
        "and whether it counts. Scores of sections you owe an assessment for are left out."
    ),
    responses=problems(401, 403, 404),
)
async def list_bid_ai_assessments(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, bid_id: BidId
) -> BidAiAssessmentList:
    raise NotImplementedProblem


@router.put(
    _BID + "/ai-assessments/{ai_assessment_id}/include-in-totals",
    operation_id="set_bid_ai_inclusion",
    summary="Count the AI's assessment in the totals",
    description=(
        "bid.manage, and the assessment visible to you (404 while you owe an assessment of the "
        "bid): include it in this bid's scores or leave it out; idempotent. A re-submission "
        "that changes a score leaves it out again. Audited bid_assessment.include_ai." + _CALL_STATE
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def set_bid_ai_inclusion(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    bid_id: BidId,
    ai_assessment_id: AiAssessmentId,
    body: BidAiInclusionUpdate,
) -> BidAiAssessment:
    raise NotImplementedProblem
