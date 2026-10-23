import json
from datetime import datetime, timezone

from app.domain.sync_logic import Classification, classify, content_hash, normalize_row, plan_batch


def row(i=1, **over):
    base = {
        "id": i,
        "account_ref": " ACC-0001 ",
        "amount_cents": 1250,
        "currency": "usd",
        "status": "Settled",
        "occurred_at": datetime(2026, 1, 2, 3, 4, 5),
    }
    return {**base, **over}


def test_normalize_is_canonical():
    n = normalize_row(row())
    assert n == {
        "source_id": 1,
        "account_ref": "ACC-0001",
        "amount_cents": 1250,
        "currency": "USD",
        "status": "settled",
        "occurred_at": "2026-01-02T03:04:05Z",
    }


def test_timezone_aware_input_is_converted_to_utc():
    aware = datetime(2026, 1, 2, 5, 4, 5, tzinfo=timezone.utc)
    assert normalize_row(row(occurred_at=aware))["occurred_at"] == "2026-01-02T05:04:05Z"


def test_hash_is_stable_and_sensitive():
    a = content_hash(normalize_row(row()))
    assert a == content_hash(normalize_row(row(account_ref="ACC-0001")))  # whitespace/case normalised away
    assert a != content_hash(normalize_row(row(amount_cents=1251)))
    assert len(a) == 64


def test_classify():
    assert classify(None, "h") is Classification.NEW
    assert classify("h", "h") is Classification.UNCHANGED
    assert classify("old", "h") is Classification.CHANGED


def test_plan_batch_splits_new_changed_unchanged():
    known_hash = content_hash(normalize_row(row(2)))
    stale_hash = "0" * 64
    plan = plan_batch(
        [row(1), row(2), row(3, amount_cents=999)],
        known={2: known_hash, 3: stale_hash},
    )
    assert [e["source_id"] for e in plan.new] == [1]
    assert [e["source_id"] for e in plan.changed] == [3]
    assert plan.unchanged_ids == [2]
    assert plan.scanned == 3
    assert {e["classification"] for e in plan.outbox} == {"new", "changed"}
    assert json.loads(plan.outbox[0]["payload"])["source_id"] == 1


def test_replaying_a_batch_after_a_crash_is_idempotent():
    """Resumability: re-planning an already-applied batch yields no new outbox rows."""
    first = plan_batch([row(1), row(2)], known={})
    known = {e["source_id"]: e["content_hash"] for e in first.outbox}
    replay = plan_batch([row(1), row(2)], known=known)
    assert replay.outbox == []
    assert replay.unchanged_ids == [1, 2]
