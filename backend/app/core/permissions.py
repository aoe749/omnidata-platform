"""Bitmask CRUD permissions.

Every role holds one integer *mask* per resource. Each bit grants one action, so
"may this role read AND export transactions?" is a single bitwise AND instead of
a join across a permission table.

    mask = READ | EXPORT          # 1 | 16 == 17
    has_action(mask, Action.READ) # True
    has_action(mask, Action.DELETE) # False

The numeric values are persisted in MySQL (``role_permissions.mask``) and
mirrored in ``db/mysql/003_seed_roles.sql`` — never renumber an existing bit.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from functools import reduce


class Action(enum.IntFlag):
    NONE = 0
    READ = 1
    CREATE = 2
    UPDATE = 4
    DELETE = 8
    EXPORT = 16


#: Public lookup consumed by the API (``/auth/me``) and the frontend.
ACTION_BITS: dict[str, int] = {a.name.lower(): int(a) for a in Action if a.value}

ALL_ACTIONS: int = reduce(lambda acc, a: acc | int(a), (a for a in Action if a.value), 0)


class Resource(str, enum.Enum):
    USERS = "users"
    TRANSACTIONS = "transactions"
    SYNC = "sync"
    METRICS = "metrics"


def has_action(mask: int, action: Action) -> bool:
    """True when *every* bit of ``action`` is present in ``mask``."""
    return (mask & int(action)) == int(action)


def describe_mask(mask: int) -> list[str]:
    """Human-readable action names granted by ``mask`` (for logs and UIs)."""
    return [name for name, bit in ACTION_BITS.items() if mask & bit]


def combine(*actions: Action) -> int:
    return reduce(lambda acc, a: acc | int(a), actions, 0)


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, resolved from MySQL on every request."""

    user_id: int
    email: str
    full_name: str
    role: str
    permissions: dict[str, int] = field(default_factory=dict)

    def can(self, resource: Resource, action: Action) -> bool:
        return has_action(self.permissions.get(resource.value, 0), action)
