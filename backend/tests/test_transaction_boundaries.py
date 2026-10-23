"""The queue worker must never hold a pooled connection or row locks across processing."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text

from app.core.config import Settings
from app.db import engines
from app.db.engines import session_scope
from app.services import ingestion_service
from app.services.ingestion_service import IngestionService


def test_session_scope_commits_on_success_and_releases_connection():
    engine = create_engine("sqlite://")
    with session_scope(engine) as session:
        session.execute(text("CREATE TABLE t (x INTEGER)"))
        session.execute(text("INSERT INTO t VALUES (1)"))
    with engine.connect() as conn:  # a new connection sees the committed row
        assert conn.execute(text("SELECT count(*) FROM t")).scalar_one() == 1


def test_session_scope_rolls_back_on_error_and_still_closes():
    engine = create_engine("sqlite://")
    with session_scope(engine) as session:
        session.execute(text("CREATE TABLE t (x INTEGER)"))
    with pytest.raises(RuntimeError):
        with session_scope(engine) as session:
            session.execute(text("INSERT INTO t VALUES (1)"))
            raise RuntimeError("boom")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM t")).scalar_one() == 0


class Recorder:
    """Fake persistence layer that records the order of scope entry/exit and repository calls."""

    def __init__(self):
        self.events = []
        self.open_scopes = 0

    @contextmanager
    def scope(self, _engine):
        self.open_scopes += 1
        self.events.append("enter")
        try:
            yield object()
            self.events.append("commit")
        except Exception:
            self.events.append("rollback")
            raise
        finally:
            self.open_scopes -= 1
            self.events.append("close")


def make_service(monkeypatch, recorder, items, fail_ingest=False):
    class FakeQueue:
        def __init__(self, _session): ...
        def reset_stale(self, _s):
            recorder.events.append("reset_stale")
            return 0
        def claim_batch(self, _n, _w):
            recorder.events.append(f"claim(open_scopes={recorder.open_scopes})")
            return items if not recorder.__dict__.get("claimed") and not recorder.__dict__.update(claimed=True) else []
        def mark_done(self, *_a): recorder.events.append("done")
        def mark_retry(self, *_a):
            recorder.events.append("retry")
            return "queued"

    class FakeMetrics:
        def __init__(self, _s): ...
        def refresh_days(self, _d): recorder.events.append("metrics")

    monkeypatch.setattr(ingestion_service, "session_scope", recorder.scope)
    monkeypatch.setattr(ingestion_service, "WorkQueueRepository", FakeQueue)
    monkeypatch.setattr(ingestion_service, "MetricsRepository", FakeMetrics)
    monkeypatch.setattr(ingestion_service, "SyncLogRepository", lambda _s: type("L", (), {"add": lambda *_: None})())

    def fake_ingest(_session, _item, payload):
        recorder.events.append(f"ingest(open_scopes={recorder.open_scopes})")
        if fail_ingest:
            raise ValueError("bad row")
        return payload.occurred_at.date()

    monkeypatch.setattr(IngestionService, "_ingest", staticmethod(fake_ingest))
    registry = engines.DatabaseRegistry(mssql=None, postgres=object(), mysql=None)  # type: ignore[arg-type]
    return IngestionService(registry, Settings(), worker_id="t")


ITEM = {
    "id": 1,
    "content_hash": "h" * 64,
    "attempts": 1,
    "payload": {
        "source_id": 1, "account_ref": "ACC-1", "amount_cents": 5,
        "currency": "USD", "status": "settled", "occurred_at": "2026-01-02T03:04:05Z",
    },
}


def test_claim_commits_and_closes_before_any_item_is_processed(monkeypatch):
    rec = Recorder()
    service = make_service(monkeypatch, rec, [ITEM])
    outcome = service.run(max_batches=1)
    assert outcome.done == 1

    claim_at = next(i for i, e in enumerate(rec.events) if e.startswith("claim"))
    ingest_at = next(i for i, e in enumerate(rec.events) if e.startswith("ingest"))
    # The claim's scope (enter .. commit, close) is fully finished before ingestion starts.
    assert rec.events[claim_at + 1 : claim_at + 3] == ["commit", "close"]
    assert claim_at < ingest_at
    assert "open_scopes=1" in rec.events[claim_at]    # claim ran in exactly one scope ...
    assert "open_scopes=1" in rec.events[ingest_at]   # ... and ingest in its own single scope
    assert rec.open_scopes == 0                       # nothing left open at the end


def test_failure_rolls_back_the_item_scope_then_records_retry_in_a_fresh_scope(monkeypatch):
    rec = Recorder()
    service = make_service(monkeypatch, rec, [ITEM], fail_ingest=True)
    outcome = service.run(max_batches=1)
    assert (outcome.done, outcome.retried) == (0, 1)

    ingest_at = next(i for i, e in enumerate(rec.events) if e.startswith("ingest"))
    assert rec.events[ingest_at + 1 : ingest_at + 3] == ["rollback", "close"]
    retry_at = rec.events.index("retry")
    assert rec.events[retry_at - 1] == "enter"  # recorded in a new scope, not the failed one
    assert rec.open_scopes == 0
