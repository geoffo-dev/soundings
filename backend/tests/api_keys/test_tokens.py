"""The key format (contract-phase5 section 3.1): ``sdg_`` + a 12-character lookup id +
``_`` + a 40-character secret, base62 from a CSPRNG; only the SHA-256 of the whole key
is stored; malformed tokens are recognised without a lookup."""

from __future__ import annotations

import hashlib
import re

import pytest

from app.api_keys.tokens import (
    BASE62,
    hash_key,
    hashes_match,
    key_prefix,
    lookup_id_of,
    lookup_id_query,
    new_key,
)
from app.schemas.api_keys import API_KEY_PATTERN

GOOD = "sdg_Ab12Cd34Ef56_" + "x" * 40


def test_new_keys_match_the_pattern_and_differ() -> None:
    keys = [new_key() for _ in range(200)]

    for lookup_id, key in keys:
        assert re.fullmatch(API_KEY_PATTERN, key)
        assert len(key) == 57
        assert key.startswith(f"sdg_{lookup_id}_")
        assert lookup_id_of(key) == lookup_id
    assert len({key for _, key in keys}) == len(keys)
    assert len({lookup_id for lookup_id, _ in keys}) == len(keys)
    # Every base62 character turns up: the alphabet isn't accidentally narrowed.
    assert set("".join(key[17:] for _, key in keys)) == set(BASE62)


def test_the_stored_hash_is_sha256_of_the_whole_key() -> None:
    assert hash_key(GOOD) == hashlib.sha256(GOOD.encode()).hexdigest()
    assert hashes_match(hash_key(GOOD), hash_key(GOOD))
    assert not hashes_match(hash_key(GOOD), hash_key(GOOD[:-1] + "y"))


@pytest.mark.parametrize(
    "token",
    [
        "",
        "sdg_",
        GOOD[:-1],  # secret one short
        GOOD + "x",  # one long
        GOOD + "\n",
        " " + GOOD,
        "SDG_Ab12Cd34Ef56_" + "x" * 40,  # the prefix is lower case
        "sdk_Ab12Cd34Ef56_" + "x" * 40,
        "sdg_Ab12Cd34Ef5_" + "x" * 41,  # lookup id one short
        "sdg_Ab12Cd34Ef56-" + "x" * 40,  # wrong separator
        "sdg_Ab12Cd34Ef5!_" + "x" * 40,
        "sdg_Ab12Cd34Ef56_" + "x" * 39 + "é",
        "sdg_Ab12Cd34Ef56_" + "x" * 39 + "\x00",
        "sdg_\uff21b12Cd34Ef56_" + "x" * 40,  # a full-width letter
        "Bearer " + GOOD,
    ],
)
def test_malformed_tokens_have_no_lookup_id(token: str) -> None:
    assert lookup_id_of(token) is None


def test_prefix_is_what_people_see() -> None:
    assert key_prefix("Ab12Cd34Ef56") == "sdg_Ab12Cd34Ef56"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("sdg_Ab12Cd34Ef56", "Ab12Cd34Ef56"),
        ("Ab12Cd34Ef56", "Ab12Cd34Ef56"),
        ("  sdg_Ab12Cd34Ef56 ", "Ab12Cd34Ef56"),
        (GOOD, "Ab12Cd34Ef56"),  # a pasted whole key is cut to its lookup id
        ("sdg_Ab12Cd34Ef56_", "Ab12Cd34Ef56"),
        ("Claude Desktop", None),
        ("sdg_Ab12", None),
        ("Ab12Cd34Ef567", None),
        ("ada@example.com", None),
    ],
)
def test_admin_search_recognises_a_prefix_or_lookup_id(query: str, expected: str | None) -> None:
    assert lookup_id_query(query) == expected
