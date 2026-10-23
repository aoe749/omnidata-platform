"""Small helpers for safe dynamic SQL (filters, sorting, LIKE patterns).

Values are *always* bound parameters. Only identifiers taken from an explicit
allow-list are ever interpolated into SQL text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WhereBuilder:
    clauses: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)

    def add(self, clause: str, **params: Any) -> None:
        self.clauses.append(clause)
        self.params.update(params)

    @property
    def sql(self) -> str:
        return ("WHERE " + " AND ".join(self.clauses)) if self.clauses else ""


def like_pattern(term: str) -> str:
    """Contains-match pattern with LIKE wildcards in ``term`` escaped (escape char: ``\\``)."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def order_by(
    sort_by: str | None,
    sort_dir: str,
    allowed: dict[str, str],
    *,
    default: str,
    tiebreak: str,
) -> str:
    """Build an ORDER BY body from a whitelist; unknown fields fall back to ``default``."""
    column = allowed.get(sort_by or "", allowed[default])
    direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
    return f"{column} {direction}, {tiebreak} {direction}"
