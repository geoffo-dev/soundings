"""Column types shared by the models."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum


def str_enum[E: StrEnum](enum_cls: type[E], name: str) -> Enum:
    """``VARCHAR`` + named ``CHECK`` constraint storing the enum *values* (e.g. ``"new"``).

    Non-native on purpose: adding a value later is a constraint swap in a migration,
    with none of Postgres' ``ALTER TYPE ... ADD VALUE`` transaction restrictions.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=max(len(member.value) for member in enum_cls),
        validate_strings=True,
        values_callable=lambda cls: [member.value for member in cls],
    )
