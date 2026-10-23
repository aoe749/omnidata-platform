"""Pure (I/O-free) logic of the resumable migration: normalise, hash, classify.

Keeping this free of database code makes the interesting decisions trivially
unit-testable.
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


class Classification(str, enum.Enum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


def normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical representation of a source row (stable key set and types)."""
    occurred: datetime = row["occurred_at"]
    if occurred.tzinfo is None:  # the source stores naive UTC timestamps
        occurred = occurred.replace(tzinfo=timezone.utc)
    return {
        "source_id": int(row["id"]),
        "account_ref": str(row["account_ref"]).strip(),
        "amount_cents": int(row["amount_cents"]),
        "currency": str(row["currency"]).strip().upper(),
        "status": str(row["status"]).strip().lower(),
        "occurred_at": occurred.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def content_hash(normalized: Mapping[str, Any]) -> str:
    """SHA-256 over the canonical JSON form; changes iff any business field changes."""
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def classify(known_hash: str | None, new_hash: str) -> Classification:
    if known_hash is None:
        return Classification.NEW
    return Classification.UNCHANGED if known_hash == new_hash else Classification.CHANGED


@dataclass
class BatchPlan:
    """What to persist for one batch of source rows."""

    new: list[dict[str, Any]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    unchanged_ids: list[int] = field(default_factory=list)
    outbox: list[dict[str, Any]] = field(default_factory=list)

    @property
    def scanned(self) -> int:
        return len(self.new) + len(self.changed) + len(self.unchanged_ids)


def plan_batch(rows: Sequence[Mapping[str, Any]], known: Mapping[int, str]) -> BatchPlan:
    """Classify a batch against the crosswalk and build the outbox entries."""
    plan = BatchPlan()
    for row in rows:
        normalized = normalize_row(row)
        digest = content_hash(normalized)
        verdict = classify(known.get(normalized["source_id"]), digest)
        if verdict is Classification.UNCHANGED:
            plan.unchanged_ids.append(normalized["source_id"])
            continue
        entry = {
            "source_id": normalized["source_id"],
            "content_hash": digest,
            "classification": verdict.value,
            "payload": json.dumps(normalized, sort_keys=True),
        }
        (plan.new if verdict is Classification.NEW else plan.changed).append(entry)
        plan.outbox.append(entry)
    return plan
