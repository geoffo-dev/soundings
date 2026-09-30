"""Status labels: the fixed stages and resolutions under each project's names.

``projects.status_labels`` stores overrides only; the resolved label is the override
or :data:`app.schemas.projects.DEFAULT_STATUS_LABELS`. A closed idea shows its
resolution's label ("Accepted"), not "Closed".
"""

from __future__ import annotations

from collections.abc import Mapping

from app.models.enums import IdeaStatus, Resolution
from app.schemas.projects import DEFAULT_STATUS_LABELS

__all__ = ["LABEL_KEYS", "apply_label_changes", "resolved_labels", "status_label"]

LABEL_KEYS: tuple[str, ...] = tuple(key.value for key in DEFAULT_STATUS_LABELS)
"""Every status and resolution value, in lifecycle order."""


def resolved_labels(overrides: Mapping[str, str]) -> dict[str, str]:
    """The label for every status and resolution (keys are the wire values)."""
    return {
        key.value: overrides.get(key.value) or label for key, label in DEFAULT_STATUS_LABELS.items()
    }


def status_label(
    overrides: Mapping[str, str], status: IdeaStatus, resolution: Resolution | None
) -> str:
    key = resolution if status is IdeaStatus.CLOSED and resolution is not None else status
    return overrides.get(key.value) or DEFAULT_STATUS_LABELS[key]


def apply_label_changes(
    overrides: Mapping[str, str], changes: Mapping[str, str | None]
) -> dict[str, str]:
    """New overrides after a PATCH: ``None`` resets a label, the default label removes
    the override, any other string sets it."""
    result = dict(overrides)
    for key, label in changes.items():
        default = DEFAULT_STATUS_LABELS[_label_key(key)]
        if label is None or label == default:
            result.pop(key, None)
        else:
            result[key] = label
    return result


def _label_key(key: str) -> IdeaStatus | Resolution:
    try:
        return IdeaStatus(key)
    except ValueError:
        return Resolution(key)
