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

from fastapi import APIRouter, status

from app.api.v1.projects import ProjectSlug
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.schemas.public import (
    AltchaChallenge,
    EmailVerified,
    PublicProject,
    PublicSubmissionCreate,
    PublicSubmissionReceipt,
    TrackedSubmission,
    TrackingRequest,
    TrackingUpdatesRequest,
    VerificationRequest,
)

router = APIRouter(prefix="/public", tags=["public"])


@router.get(
    "/projects/{slug}",
    operation_id="get_public_project",
    summary="The public form's project",
    description=(
        "Public (public.submit, c8). The project's name, intro, what the form asks for "
        "and its effective branding. 404 when the form is off, the project is archived or "
        "unknown, or public submission is off for the instance (no hint which)."
    ),
    responses=problems(404),
)
async def get_public_project(slug: ProjectSlug) -> PublicProject:
    raise NotImplementedProblem


@router.get(
    "/projects/{slug}/altcha",
    operation_id="get_altcha_challenge",
    summary="An ALTCHA challenge",
    description=(
        "Public (c8). A fresh proof-of-work challenge for the ALTCHA widget (expires after "
        "SOUNDINGS_ALTCHA_EXPIRY; a solution is accepted once). Throttled per client IP "
        "(429 too_many_attempts with Retry-After)."
    ),
    responses=problems(404, 429),
)
async def get_altcha_challenge(slug: ProjectSlug) -> AltchaChallenge:
    raise NotImplementedProblem


@router.post(
    "/projects/{slug}/submissions",
    operation_id="submit_public_idea",
    status_code=status.HTTP_201_CREATED,
    summary="Send an idea through the public form",
    description=(
        "Public (c8). Checks in order: content type (415) -> body (422) -> form available "
        "(404) -> per-IP limit (429) -> email required (422 email_required) -> ALTCHA "
        "(422 challenge_failed: invalid, expired, for another form or already used) -> "
        "per-project limit (429). Creates the idea in New (held while it waits for email "
        "confirmation or moderation), the private tracking link (shown once, here) and, "
        "with an address, an email asking to confirm it."
    ),
    responses=problems(404, 415, 422, 429),
)
async def submit_public_idea(
    slug: ProjectSlug, body: PublicSubmissionCreate
) -> PublicSubmissionReceipt:
    raise NotImplementedProblem


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
async def track_submission(body: TrackingRequest) -> TrackedSubmission:
    raise NotImplementedProblem


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
async def set_submission_updates(body: TrackingUpdatesRequest) -> TrackedSubmission:
    raise NotImplementedProblem


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
async def resend_verification_email(body: TrackingRequest) -> TrackedSubmission:
    raise NotImplementedProblem


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
async def erase_tracked_submission(body: TrackingRequest) -> None:
    raise NotImplementedProblem


@router.post(
    "/verify-email",
    operation_id="verify_submission_email",
    summary="Confirm a submitter's address",
    description=(
        "Public (public.track, c9): the token from the confirmation email "
        "(/verify#<token>, valid 3 days), posted when the person clicks Confirm (never "
        "on page load). Confirms the address (idempotent); an idea held for confirmation "
        "moves on to moderation or to the team. Works while public submission is on for "
        "the instance, even if the project's form was turned off since. 404 for an "
        "invalid, expired or used-up token (the submission was erased, deleted or its "
        "address changed). Throttled per client IP (429)."
    ),
    responses=problems(404, 415, 422, 429),
)
async def verify_submission_email(body: VerificationRequest) -> EmailVerified:
    raise NotImplementedProblem
