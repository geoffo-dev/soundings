"""The public form, its ALTCHA challenge, tracking links and email confirmation.

No session needed: the project setting (``public.submit``, c8) or the token in the
request body (``public.track``, c9) is the authority, and nothing private is ever
returned. Tokens travel in request bodies, never in URLs: tracking and confirmation
links put them after ``#`` (``/track#<token>``, ``/verify#<token>``) and the SPA posts
them. Every ``POST``/``PUT`` here needs ``Content-Type: application/json`` (else 415
``unsupported_media_type``): that type makes a cross-site browser request need a CORS
preflight, which the API never grants, so another site can't submit or confirm
through its visitors' browsers. Business rules: docs/api/contract-phase4.md sections
3.5-3.9.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.api.v1.projects import ProjectSlug
from app.api.v1.responses import problems
from app.auth import altcha
from app.auth.public_form import JsonOnlyRoute, check_throttle
from app.auth.throttle import (
    ALTCHA_THROTTLE,
    PUBLIC_FORM_THROTTLE,
    PUBLIC_REPLY_THROTTLE,
    PUBLIC_TOKEN_THROTTLE,
)
from app.config import Settings
from app.db import SessionDep
from app.models.base import utcnow
from app.public import forms, submit, tracking
from app.schemas.public import (
    AltchaChallenge,
    EmailVerified,
    PublicProject,
    PublicSubmissionCreate,
    PublicSubmissionReceipt,
    TrackedSubmission,
    TrackingReplyRequest,
    TrackingRequest,
    TrackingUpdatesRequest,
    VerificationRequest,
)

# Every write here must be application/json (415 before the body is read).
router = APIRouter(prefix="/public", tags=["public"], route_class=JsonOnlyRoute)

_TOO_MANY_CHALLENGES = "Too many requests from your network. Wait a minute and try again."
_TOO_MANY_LINK_REQUESTS = "Too many requests from your network. Wait a minute and try again."
_TOO_MANY_FORM_REQUESTS = "Too many requests from your network. Wait a minute and try again."
_TOO_MANY_REPLIES = "Too many replies from your network. Try again later."


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _form_throttle(request: Request) -> None:
    """The form, challenge and submission routes share one per-IP throttle, counted
    before the form is looked up: an unknown or closed form counts too, so open forms
    can't be probed at speed (only the form's own limits come after the lookup)."""
    check_throttle(
        request,
        PUBLIC_FORM_THROTTLE,
        detail=_TOO_MANY_FORM_REQUESTS,
        event="public form request refused",
    )


def _link_throttle(request: Request) -> None:
    """The tracking and confirmation routes share one per-IP throttle, counted before
    the token is looked up (it bounds load; tokens can't be guessed)."""
    check_throttle(
        request,
        PUBLIC_TOKEN_THROTTLE,
        detail=_TOO_MANY_LINK_REQUESTS,
        event="public link request refused",
    )


@router.get(
    "/projects/{slug}",
    operation_id="get_public_project",
    summary="The public form's project",
    description=(
        "Public (public.submit, c8). The project's name, intro, what the form asks for "
        "and its effective branding. 404 when the form is off, the project is archived or "
        "unknown, or public submission is off for the instance (no hint which). "
        "Throttled per client IP with the challenge and submission routes, before the "
        "form is looked up (429 too_many_attempts with Retry-After)."
    ),
    responses=problems(404, 429),
)
async def get_public_project(
    request: Request, session: SessionDep, slug: ProjectSlug
) -> PublicProject:
    _form_throttle(request)
    settings = _settings(request)
    project = await forms.load_form(session, settings, slug)
    return await forms.public_project(session, settings, project)


@router.get(
    "/projects/{slug}/altcha",
    operation_id="get_altcha_challenge",
    summary="An ALTCHA challenge",
    description=(
        "Public (c8). A fresh proof-of-work challenge for the ALTCHA widget (expires after "
        "SOUNDINGS_ALTCHA_EXPIRY; a solution is accepted once). Throttled per client IP "
        "(429 too_many_attempts with Retry-After): with the form and submission routes "
        "before the form is looked up, and challenges on their own after."
    ),
    responses=problems(404, 429),
)
async def get_altcha_challenge(
    request: Request, session: SessionDep, slug: ProjectSlug
) -> AltchaChallenge:
    _form_throttle(request)
    settings = _settings(request)
    project = await forms.load_form(session, settings, slug)
    check_throttle(
        request,
        ALTCHA_THROTTLE,
        detail=_TOO_MANY_CHALLENGES,
        event="altcha challenge refused",
        log_fields={"project_id": str(project.id)},
    )
    return AltchaChallenge.model_validate(
        altcha.new_challenge(settings, project.slug, now=utcnow())
    )


@router.post(
    "/projects/{slug}/submissions",
    operation_id="submit_public_idea",
    status_code=status.HTTP_201_CREATED,
    summary="Send an idea through the public form",
    description=(
        "Public (c8). Checks in order: content type (415) -> body (422) -> per-IP form "
        "requests, shared with the form and challenge routes (429) -> form available "
        "(404) -> per-IP limit (429) -> email required (422 email_required) -> ALTCHA "
        "(422 challenge_failed: invalid, expired, for another form or already used) -> "
        "per-project limit (429). Creates the idea in New (held while it waits for email "
        "confirmation or moderation), the private tracking link (shown once, here) and, "
        "with an address, an email asking to confirm it."
    ),
    responses=problems(404, 415, 422, 429),
)
async def submit_public_idea(
    request: Request, session: SessionDep, slug: ProjectSlug, body: PublicSubmissionCreate
) -> PublicSubmissionReceipt:
    _form_throttle(request)
    return await submit.submit(session, _settings(request), request, slug, body, now=utcnow())


@router.post(
    "/track",
    operation_id="track_submission",
    summary="Open a tracking link",
    description=(
        "Public (public.track, c9): the submitter's own idea, its status and status "
        "history; nothing else. 404 for an unknown or erased token (no hint which). "
        "Throttled per client IP (429)."
    ),
    responses=problems(404, 415, 422, 429),
)
async def track_submission(
    request: Request, session: SessionDep, body: TrackingRequest
) -> TrackedSubmission:
    _link_throttle(request)
    settings = _settings(request)
    found = await tracking.find(session, settings, body.token)
    return await tracking.tracked_submission(session, settings, found, now=utcnow())


@router.put(
    "/track/updates",
    operation_id="set_submission_updates",
    summary="Turn status emails on or off",
    description=(
        "Public (c9). wants_updates=true needs an address on file (409 no_email); emails "
        "go out only once the address is confirmed. Idempotent."
    ),
    responses=problems(404, 409, 415, 422, 429),
)
async def set_submission_updates(
    request: Request, session: SessionDep, body: TrackingUpdatesRequest
) -> TrackedSubmission:
    _link_throttle(request)
    return await tracking.set_updates(
        session, _settings(request), body.token, body.wants_updates, now=utcnow()
    )


@router.post(
    "/track/verification-email",
    operation_id="resend_verification_email",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send the confirmation email again",
    description=(
        "Public (c9). For an unconfirmed address on file (409 no_email, already_verified); "
        "at most 3 confirmation emails per submission per 24 hours (429 too_many_attempts "
        "with Retry-After); 409 smtp_not_configured when email is off."
    ),
    responses=problems(404, 409, 415, 422, 429),
)
async def resend_verification_email(
    request: Request, session: SessionDep, body: TrackingRequest
) -> TrackedSubmission:
    _link_throttle(request)
    return await tracking.resend_confirmation(session, _settings(request), body.token, now=utcnow())


@router.post(
    "/track/erase",
    operation_id="erase_tracked_submission",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete my details",
    description=(
        "Public (c9): the submitter erases their own name, address and private link, "
        "exactly like an admin's erase_submitter (UK GDPR); the idea stays with the "
        "team. The link stops working at once (a second call is 404). Audited without "
        "an actor (submission.erase, reason submitter). Throttled per client IP (429)."
    ),
    responses=problems(404, 415, 422, 429),
)
async def erase_tracked_submission(
    request: Request, session: SessionDep, body: TrackingRequest
) -> None:
    _link_throttle(request)
    await tracking.erase_own_details(session, _settings(request), body.token, now=utcnow())


@router.post(
    "/track/messages",
    operation_id="send_tracking_reply",
    status_code=status.HTTP_201_CREATED,
    summary="Reply to the team",
    description=(
        "Public (public.track, c9): the submitter's reply to the team from their tracking page, "
        "once the team has written to them (409 awaiting_team: the public never starts a "
        "conversation, and at most 10 replies follow each team message). Plain text (1-4,000 "
        "characters), untrusted everywhere. Checks in order: content type (415) -> body (422) "
        "-> per-IP link requests, shared with the other tracking routes (429) -> token (404, "
        "unknown and erased alike, or public submission off) -> 30 replies per client IP an "
        "hour (429) -> 409 project_archived, awaiting_team, conversation_full (100 messages) "
        "-> 10 replies per submission in 24 hours (429 too_many_attempts with Retry-After). "
        "Notifies the team (submitter_replied, never the text). Not audited (no actor; the "
        "message is the record). Returns the tracking page."
    ),
    responses=problems(404, 409, 415, 422, 429),
)
async def send_tracking_reply(
    request: Request, session: SessionDep, body: TrackingReplyRequest
) -> TrackedSubmission:
    _link_throttle(request)
    settings = _settings(request)
    found = await tracking.find(session, settings, body.token, lock=True)
    check_throttle(
        request,
        PUBLIC_REPLY_THROTTLE,
        detail=_TOO_MANY_REPLIES,
        event="public reply refused",
        log_fields={"idea_id": str(found[1].id)},
    )
    return await tracking.reply(session, settings, found, body.body, now=utcnow())


@router.post(
    "/track/forget-email",
    operation_id="forget_submission_email",
    summary="Remove my email address",
    description=(
        "Public (public.track, c9; Phase 11 review M2): the submitter removes their address, "
        "exactly as the 3-day rule for unconfirmed addresses does: the address, its "
        "confirmation and the status-email opt-in are cleared and every email of this idea to "
        "it is deleted, queued and sent (no message, link or status email follows). The "
        "tracking link, the idea and the conversation stay (team messages then reach the "
        "tracking page only). Idempotent without an address. 409 awaiting_confirmation while "
        "the idea waits for that address to be confirmed (it reaches the team only then; "
        "delete your details to withdraw it). Not audited (like the 3-day rule). Checks in "
        "order: 415 -> 422 -> per-IP link requests (429) -> token (404) -> 409. Returns the "
        "tracking page."
    ),
    responses=problems(404, 409, 415, 422, 429),
)
async def forget_submission_email(
    request: Request, session: SessionDep, body: TrackingRequest
) -> TrackedSubmission:
    _link_throttle(request)
    return await tracking.forget_email(session, _settings(request), body.token, now=utcnow())


@router.post(
    "/verify-email",
    operation_id="verify_submission_email",
    summary="Confirm a submitter's address",
    description=(
        "Public (public.track, c9): the token from the confirmation email "
        "(/verify#<token>, valid 3 days), posted when the person clicks Confirm (never "
        "on page load). Confirms the address (idempotent); an idea held for confirmation "
        "moves on to moderation or to the team. Phase 11: the first confirmation also emails "
        "the private tracking link to that address (tracking_link_emailed; never again "
        "after). Works while public submission is on for "
        "the instance, even if the project's form was turned off since. 404 for an "
        "invalid, expired or used-up token (the submission was erased, deleted or its "
        "address changed). Throttled per client IP (429)."
    ),
    responses=problems(404, 415, 422, 429),
)
async def verify_submission_email(
    request: Request, session: SessionDep, body: VerificationRequest
) -> EmailVerified:
    _link_throttle(request)
    return await tracking.verify_email(session, _settings(request), body.token, now=utcnow())
