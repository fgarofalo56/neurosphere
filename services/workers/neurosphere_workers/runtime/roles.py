"""``NS_WORKER_ROLES`` parsing: the role names, ``all`` expansion and refusal of unknown roles."""

from __future__ import annotations

from typing import Final

__all__ = [
    "ALL_ROLES_KEYWORD",
    "OPT_IN_ROLES",
    "ROLE_NAMES",
    "RoleConfigError",
    "UnknownRoleError",
    "parse_roles",
]

ALL_ROLES_KEYWORD: Final = "all"

#: The wire contract roles, in start order (PRP-29). ``all`` expands to exactly this tuple.
ROLE_NAMES: Final[tuple[str, ...]] = (
    "ingestion",
    "projections",
    "aggregates",
    "actions",
    "hitl_timers",
    "lifecycle",
    "recommendations",
    "evaluation",
    "gateway_poll",
)

#: Roles that must be named explicitly: ``all`` does not start them (they need extra
#: configuration, e.g. a producer secret, that an existing ``all`` deployment does not have).
OPT_IN_ROLES: Final[tuple[str, ...]] = ("gateway_poll",)


class UnknownRoleError(ValueError):
    """``NS_WORKER_ROLES`` names a role that does not exist: the process refuses to start."""

    def __init__(self, unknown: tuple[str, ...]) -> None:
        super().__init__(
            f"unknown worker role(s): {', '.join(unknown)}; "
            f"valid roles are {', '.join(ROLE_NAMES)} or '{ALL_ROLES_KEYWORD}'"
        )
        self.unknown = unknown


class RoleConfigError(Exception):
    """A configured role cannot be built because its settings are missing or invalid.

    Terminal for that role (not retried): the role is reported ``failed`` with ``reason`` and
    readiness stays false, while the other roles keep running. ``reason`` is a machine code.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def parse_roles(raw: str | None) -> tuple[str, ...]:
    """The roles to run, de-duplicated in canonical order.

    ``None``/blank -> ``()`` (idle). ``all`` expands to :data:`ROLE_NAMES` minus
    :data:`OPT_IN_ROLES`. Any unknown name
    raises :class:`UnknownRoleError` (nothing is started).
    """
    if raw is None or not raw.strip():
        return ()
    names = [part.strip().lower() for part in raw.split(",") if part.strip()]
    unknown = tuple(
        dict.fromkeys(n for n in names if n != ALL_ROLES_KEYWORD and n not in ROLE_NAMES)
    )
    if unknown:
        raise UnknownRoleError(unknown)
    wanted = set(names)
    if ALL_ROLES_KEYWORD in wanted:
        wanted.update(role for role in ROLE_NAMES if role not in OPT_IN_ROLES)
    return tuple(role for role in ROLE_NAMES if role in wanted)
