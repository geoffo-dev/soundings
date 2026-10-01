"""Phase 4 settings: public submission, ALTCHA and branding uploads (contract-phase4
section 3.12; the chart's names)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.config import BRANDING_UPLOAD_MAX_BYTES, Settings
from tests.conftest import make_settings


def test_defaults() -> None:
    settings = make_settings()

    assert settings.public_submission_enabled is True
    assert settings.public_submissions_per_ip == 10
    assert settings.public_submissions_per_project == 100
    assert settings.altcha_cost == 5_000
    assert settings.altcha_expiry == timedelta(minutes=30)
    assert settings.branding_max_upload_bytes == 512 * 1024


def test_chart_environment_names_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "SOUNDINGS_PUBLIC_SUBMISSION_ENABLED": "false",
        "SOUNDINGS_PUBLIC_SUBMISSIONS_PER_IP": "5",
        "SOUNDINGS_PUBLIC_SUBMISSIONS_PER_PROJECT": "50",
        "SOUNDINGS_ALTCHA_COST": "20000",
        "SOUNDINGS_ALTCHA_EXPIRY": "PT10M",
        "SOUNDINGS_BRANDING_MAX_UPLOAD_BYTES": "262144",
    }.items():
        monkeypatch.setenv(name, value)

    settings = Settings()

    assert settings.public_submission_enabled is False
    assert (settings.public_submissions_per_ip, settings.public_submissions_per_project) == (5, 50)
    assert settings.altcha_cost == 20_000
    assert settings.altcha_expiry == timedelta(minutes=10)
    assert settings.branding_max_upload_bytes == 256 * 1024


@pytest.mark.parametrize(
    "overrides",
    [
        {"public_submissions_per_ip": 0},
        {"public_submissions_per_project": 0},
        {"altcha_cost": 999},
        {"altcha_cost": 1_000_001},
        {"altcha_expiry": timedelta(seconds=59)},
        {"altcha_expiry": timedelta(days=2)},
        {"branding_max_upload_bytes": 1024},
        {"branding_max_upload_bytes": BRANDING_UPLOAD_MAX_BYTES + 1},
    ],
)
def test_out_of_range_values_are_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**overrides)


def test_an_upload_always_fits_in_a_request_body() -> None:
    from app.middleware import MAX_REQUEST_BODY_BYTES

    assert BRANDING_UPLOAD_MAX_BYTES < MAX_REQUEST_BODY_BYTES
