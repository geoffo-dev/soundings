"""The submitter's secrets and the public throttles, as units (contract-phase4 section
3.7): tracking tokens (random, hashed, sealed) and confirmation tokens (signed,
expiring, bound to the address)."""

from __future__ import annotations

import base64
import json
import re
from datetime import timedelta
from uuid import uuid4

from pydantic import SecretStr

from app.auth.public_form import honeypot_filled, is_json
from app.auth.sealing import seal
from app.auth.submission_tokens import (
    CONFIRMATION_VALIDITY,
    email_digest,
    make_confirmation_token,
    new_tracking_token,
    read_confirmation_token,
    seal_tracking_token,
    tracking_token_hash,
    unseal_tracking_token,
)
from app.auth.throttle import Throttle
from app.models.base import utcnow
from app.schemas.public import TRACKING_TOKEN_PATTERN, VERIFICATION_TOKEN_PATTERN
from tests.conftest import make_settings

SETTINGS = make_settings(secret_key="unit-test-secret-key-0123456789abcdef")
OTHER = SETTINGS.model_copy(update={"secret_key": SecretStr("another-secret-key-0123456789abcd")})


def test_tracking_tokens_are_random_43_url_safe_characters() -> None:
    tokens = {new_tracking_token() for _ in range(50)}

    assert len(tokens) == 50
    assert all(re.fullmatch(TRACKING_TOKEN_PATTERN, token) for token in tokens)


def test_tracking_tokens_are_kept_hashed_and_sealed_for_one_purpose() -> None:
    token = new_tracking_token()
    sealed = seal_tracking_token(SETTINGS, token)

    assert len(tracking_token_hash(token)) == 64
    assert token not in sealed
    assert len(sealed) <= 255
    assert unseal_tracking_token(SETTINGS, sealed) == token
    assert unseal_tracking_token(OTHER, sealed) is None
    # Sealed for another purpose, it doesn't open as a tracking token.
    assert unseal_tracking_token(SETTINGS, seal(SETTINGS, "session-id-token", b"x" * 43)) is None


def test_a_confirmation_token_round_trips_until_it_expires() -> None:
    now = utcnow()
    submission_id = uuid4()
    token = make_confirmation_token(SETTINGS, submission_id, "Jo@Example.org", now=now)

    assert re.fullmatch(VERIFICATION_TOKEN_PATTERN, token)
    claim = read_confirmation_token(SETTINGS, token, now=now + CONFIRMATION_VALIDITY / 2)
    assert claim is not None
    assert claim.submission_id == submission_id
    assert claim.email_digest == email_digest("jo@example.org")
    expired = now + CONFIRMATION_VALIDITY + timedelta(seconds=1)
    assert read_confirmation_token(SETTINGS, token, now=expired) is None


def test_a_confirmation_token_holds_no_address() -> None:
    token = make_confirmation_token(SETTINGS, uuid4(), "jo@example.org", now=utcnow())
    body = token.split(".")[0]
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))

    assert set(payload) == {"v", "s", "e", "x"}
    assert "jo" not in json.dumps(payload)


def test_forged_and_malformed_confirmation_tokens_are_refused() -> None:
    now = utcnow()
    token = make_confirmation_token(SETTINGS, uuid4(), "jo@example.org", now=now)
    body, mac = token.split(".")

    def signed(payload: dict[str, object]) -> str:
        """A payload signed with the right key (as if the key had leaked)."""
        from app.auth import submission_tokens as module

        raw = module._b64(json.dumps(payload).encode())
        return f"{raw}.{module._mac(SETTINGS, raw)}"

    for bad in [
        make_confirmation_token(OTHER, uuid4(), "jo@example.org", now=now),
        f"{body}.{mac[::-1]}",
        f"{body}x.{mac}",
        body,
        f"{body}.{mac}.{mac}",
        "é" * 20 + "." + mac,
        "a" * 600 + "." + mac,
        signed({"v": 2, "s": str(uuid4()), "e": "0" * 16, "x": 9_999_999_999}),
        signed({"v": 1, "s": "not-a-uuid", "e": "0" * 16, "x": 9_999_999_999}),
        signed({"v": 1, "s": str(uuid4()), "e": "0" * 16, "x": "soon"}),
        signed({"v": 1, "s": str(uuid4()), "e": "0" * 16, "x": True}),
        signed({"v": 1, "s": str(uuid4()), "e": 7, "x": 9_999_999_999}),
        signed({"v": 1, "s": str(uuid4()), "e": "0" * 16, "x": 9_999_999_999, "extra": 1}),
        signed([1, 2, 3]),  # type: ignore[arg-type]
    ]:
        assert read_confirmation_token(SETTINGS, bad, now=now) is None, bad


def test_only_application_json_is_json() -> None:
    assert is_json("application/json")
    assert is_json("Application/JSON; charset=utf-8")
    for other in (
        None,
        "",
        "text/plain",
        "application/x-www-form-urlencoded",
        "json",
        "application/json-seq",
        "application/ld+json",
    ):
        assert not is_json(other), other


def test_any_honeypot_value_counts() -> None:
    assert not honeypot_filled("")
    assert honeypot_filled(" ")
    assert honeypot_filled("x" * 5_000)


def test_a_refused_key_is_noticed_once_per_period() -> None:
    now = [0.0]
    throttle = Throttle(1, 60.0, clock=lambda: now[0])

    assert throttle.first_notice("a", 3600.0)
    assert not throttle.first_notice("a", 3600.0)
    assert throttle.first_notice("b", 3600.0)
    now[0] = 3600.0
    assert throttle.first_notice("a", 3600.0)


def test_noticed_keys_stay_bounded() -> None:
    throttle = Throttle(1, 60.0, max_keys=3)

    for key in "abcdef":
        assert throttle.first_notice(key, 3600.0)

    assert len(throttle._noticed_at) <= 3
