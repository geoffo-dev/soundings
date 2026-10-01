"""ALTCHA (contract-phase4 section 3.5 step 5): a signed PoW v2 challenge bound to the
form, verified strictly, accepted once, expiring; anything else is 422
``challenge_failed`` (never a 500)."""

from __future__ import annotations

import base64
import json
from datetime import timedelta
from typing import Any

import altcha as altcha_lib
import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import altcha
from app.config import Settings
from app.models.base import utcnow
from app.models.idea import Idea
from app.models.public import AltchaUsedChallenge
from tests.public.conftest import (
    PUBLIC,
    Form,
    Team,
    Visitor,
    assert_problem,
    challenge_for,
    payload_for,
    send,
)

pytestmark = pytest.mark.usefixtures("form")


def encode(value: Any) -> str:
    return base64.b64encode(json.dumps(value).encode()).decode()


async def ideas(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(Idea)) or 0)


async def test_the_challenge_is_the_widgets_format_bound_to_the_form(
    anon: httpx.AsyncClient, team: Team, settings: Settings
) -> None:
    response = await anon.get(f"{PUBLIC}/projects/{team.slug}/altcha")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"parameters", "signature"}
    parameters = body["parameters"]
    assert set(parameters) == {
        "algorithm", "cost", "keyLength", "keyPrefix", "nonce", "salt", "expiresAt", "data",
    }  # fmt: skip
    assert parameters["algorithm"] == "PBKDF2/SHA-256"
    assert parameters["cost"] == settings.altcha_cost
    assert parameters["keyPrefix"] == "00"
    assert parameters["data"] == {"project": team.slug}
    expires = parameters["expiresAt"] - utcnow().timestamp()
    assert (
        settings.altcha_expiry.total_seconds() - 5
        < expires
        <= settings.altcha_expiry.total_seconds()
    )
    assert response.headers["cache-control"] == "no-store"


async def test_a_solved_challenge_is_accepted_once(
    anon: httpx.AsyncClient, team: Team, db_session: AsyncSession
) -> None:
    payload = payload_for(await challenge_for(anon, team.slug))

    first = await send(anon, team.slug, altcha=payload)
    again = await send(anon, team.slug, altcha=payload, title="Another idea")

    assert first.status_code == 201, first.text
    assert_problem(again, 422, "challenge_failed")
    assert await ideas(db_session) == 1
    spent = await db_session.scalar(select(func.count()).select_from(AltchaUsedChallenge))
    assert spent == 1


async def test_an_expired_challenge_is_refused(
    anon: httpx.AsyncClient, team: Team, settings: Settings, db_session: AsyncSession
) -> None:
    old = altcha.new_challenge(
        settings, team.slug, now=utcnow() - settings.altcha_expiry - timedelta(seconds=1)
    )

    response = await send(anon, team.slug, altcha=payload_for(old))

    assert_problem(response, 422, "challenge_failed")
    assert await ideas(db_session) == 0


async def test_a_challenge_for_another_form_is_refused(
    anon: httpx.AsyncClient, team: Team, form: Form, db_session: AsyncSession
) -> None:
    from tests.factories import make_project

    other = await form(await make_project(db_session, slug="other-form", key="OTH"))
    foreign = payload_for(await challenge_for(anon, other.slug))

    response = await send(anon, team.slug, altcha=foreign)

    assert_problem(response, 422, "challenge_failed")
    assert await ideas(db_session) == 0


async def test_a_challenge_signed_with_another_key_is_refused(
    anon: httpx.AsyncClient, team: Team, settings: Settings
) -> None:
    other = settings.model_copy(
        update={"secret_key": SecretStr("another-secret-key-for-the-test-xx")}
    )
    forged = altcha.new_challenge(other, team.slug, now=utcnow())

    assert_problem(await send(anon, team.slug, altcha=payload_for(forged)), 422, "challenge_failed")


@pytest.mark.parametrize(
    "tamper",
    [
        lambda p: p | {"cost": 1},
        lambda p: p | {"expiresAt": p["expiresAt"] + 3600},
        lambda p: p | {"data": {"project": "other-form"}},
        lambda p: p | {"keyPrefix": ""},
        lambda p: {k: v for k, v in p.items() if k != "expiresAt"},
    ],
    ids=["cost", "expiry", "data", "prefix", "no-expiry"],
)
async def test_tampered_parameters_are_refused(
    anon: httpx.AsyncClient, team: Team, tamper: Any
) -> None:
    challenge = await challenge_for(anon, team.slug)
    challenge["parameters"] = tamper(challenge["parameters"])

    response = await send(anon, team.slug, altcha=payload_for(challenge))

    assert_problem(response, 422, "challenge_failed")


async def test_a_solution_for_another_challenge_is_refused(
    anon: httpx.AsyncClient, team: Team
) -> None:
    one = await challenge_for(anon, team.slug)
    two = await challenge_for(anon, team.slug)
    solved_one = json.loads(base64.b64decode(payload_for(one)))
    mixed = {"challenge": two, "solution": solved_one["solution"]}

    assert_problem(await send(anon, team.slug, altcha=encode(mixed)), 422, "challenge_failed")


async def test_a_wrong_counter_is_refused(anon: httpx.AsyncClient, team: Team) -> None:
    challenge = await challenge_for(anon, team.slug)
    solved = json.loads(base64.b64decode(payload_for(challenge)))
    solved["solution"]["counter"] += 1

    assert_problem(await send(anon, team.slug, altcha=encode(solved)), 422, "challenge_failed")


def _malformed(challenge: dict[str, Any]) -> list[Any]:
    solved = json.loads(base64.b64decode(payload_for(challenge)))

    def with_solution(**values: Any) -> dict[str, Any]:
        return {**solved, "solution": {**solved["solution"], **values}}

    def with_signature(value: Any) -> dict[str, Any]:
        return {**solved, "challenge": {**solved["challenge"], "signature": value}}

    return [
        [],
        "just a string",
        {"challenge": challenge},
        {"solution": solved["solution"]},
        with_solution(counter=2**32),  # the library packs a uint32: struct.error
        with_solution(counter=-1),
        with_solution(counter="7"),
        with_solution(counter=True),
        with_solution(counter=1.5),
        with_solution(derivedKey="zz" * 32),
        with_solution(derivedKey="é" * 64),
        with_signature("é" * 64),  # non-ASCII: hmac.compare_digest raises TypeError
        with_signature(None),
        with_signature(123),
        {**solved, "challenge": {**solved["challenge"], "parameters": []}},
        {
            **solved,
            "challenge": {
                **solved["challenge"],
                "parameters": {**challenge["parameters"], "algorithm": "SCRYPT"},
            },
        },
        {
            **solved,
            "challenge": {
                **solved["challenge"],
                "parameters": {**challenge["parameters"], "extra": 1},
            },
        },
        {
            **solved,
            "challenge": {
                **solved["challenge"],
                "parameters": {**challenge["parameters"], "nonce": "xyz"},
            },
        },
    ]


@pytest.mark.parametrize("case", range(18))
async def test_malformed_payloads_are_refused_not_crashing(
    anon: httpx.AsyncClient, team: Team, case: int
) -> None:
    payload = _malformed(await challenge_for(anon, team.slug))[case]

    response = await send(anon, team.slug, altcha=encode(payload))

    assert_problem(response, 422, "challenge_failed")


@pytest.mark.parametrize("payload", ["AAAA", "e30=", "bm90IGpzb24=", "////", "a" * 4096])
async def test_payloads_that_are_not_json_objects_are_refused(
    anon: httpx.AsyncClient, team: Team, payload: str
) -> None:
    assert_problem(await send(anon, team.slug, altcha=payload), 422, "challenge_failed")


async def test_url_safe_base64_is_accepted(anon: httpx.AsyncClient, team: Team) -> None:
    payload = payload_for(await challenge_for(anon, team.slug))
    url_safe = payload.replace("+", "-").replace("/", "_").rstrip("=")

    response = await send(anon, team.slug, altcha=url_safe)

    assert response.status_code == 201, response.text


async def test_concurrent_replays_accept_one(
    app: Any, visitor: Visitor, team: Team, db_session: AsyncSession
) -> None:
    import asyncio

    client = await visitor()
    payload = payload_for(await challenge_for(client, team.slug))
    clients = [await visitor(f"198.51.100.{n}") for n in range(1, 5)]

    responses = await asyncio.gather(
        *(send(c, team.slug, altcha=payload, title=f"Idea {n}") for n, c in enumerate(clients))
    )

    assert sorted(r.status_code for r in responses) == [201, 422, 422, 422]
    assert await ideas(db_session) == 1


def test_the_hmac_key_is_derived_from_the_secret_key(settings: Settings) -> None:
    key = altcha.hmac_key(settings)
    other = settings.model_copy(
        update={"secret_key": SecretStr("another-secret-key-for-the-test-xx")}
    )

    assert len(key) == 64
    assert int(key, 16) >= 0
    assert altcha.hmac_key(other) != key
    assert settings.secret_key.get_secret_value() not in key


def test_the_library_alone_would_accept_a_replay(settings: Settings) -> None:
    """Why ``altcha_used_challenges`` exists (research R1 section 7)."""
    challenge = altcha_lib.Challenge.from_dict(altcha.new_challenge(settings, "x", now=utcnow()))
    solution = altcha_lib.solve_challenge(challenge)
    assert solution is not None
    payload = altcha_lib.Payload(challenge, solution).to_base64()

    assert altcha_lib.verify_solution(payload, altcha.hmac_key(settings)).verified
    assert altcha_lib.verify_solution(payload, altcha.hmac_key(settings)).verified
