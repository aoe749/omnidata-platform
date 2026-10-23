"""Resumable data migration: MS SQL source -> classified outbox -> PostgreSQL queue.

Design
------
* **One transaction per batch.** The batch's crosswalk updates, outbox rows and the
  checkpoint cursor commit atomically. A crash therefore leaves the cursor exactly
  where the last *fully applied* batch ended, and ``run()`` simply continues from it.
* **Single runner.** A session-scoped ``sp_getapplock`` ensures only one process
  migrates at a time (a second caller gets :class:`MigrationAlreadyRunning`).
* **At-least-once, idempotent hand-off.** ``publish_pending`` writes to PostgreSQL
  first and marks the outbox rows published second. If the second step fails the
  rows are published again, which the ``(source_id, content_hash)`` unique key
  in the queue turns into a no-op.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.engines import DatabaseRegistry, session_scope
from app.domain.sync_logic import plan_batch
from app.repositories.mssql_repo import MigrationStateRepository
from app.repositories.postgres_repo import SyncLogRepository, WorkQueueRepository

log = logging.getLogger(__name__)

LOCK_RESOURCE = "omnidata:migration"


class MigrationAlreadyRunning(RuntimeError):
    """Another process currently holds the migration lock."""


@dataclass(frozen=True)
class PublishOutcome:
    batches: int
    published: int


class MigrationService:
    def __init__(self, registry: DatabaseRegistry, settings: Settings) -> None:
        self._mssql = registry.mssql
        self._postgres = registry.postgres
        self._settings = settings

    # ------------------------------------------------------------ migration
    def run(self, max_batches: int | None = None) -> dict:
        """Run (or resume) a migration; returns the run row as stored in MS SQL.

        ``max_batches`` bounds the work done per call; an unfinished run stays
        ``running`` and the next call continues from its cursor.
        """
        with self._exclusive_lock():
            run_id, cursor, resumed = self._start_or_resume()
            batches = 0
            while max_batches is None or batches < max_batches:
                try:
                    with session_scope(self._mssql) as session:
                        repo = MigrationStateRepository(session)
                        rows = repo.fetch_source_after(cursor, self._settings.migration_batch_size)
                        if not rows:
                            repo.mark_completed(run_id)
                            break
                        high = int(rows[-1]["id"])
                        plan = plan_batch(rows, repo.known_hashes(cursor, high))
                        repo.upsert_crosswalk(run_id, plan.new, plan.changed, plan.unchanged_ids)
                        repo.insert_outbox(run_id, plan.outbox)
                        repo.advance(run_id, high, len(plan.new), len(plan.changed), len(plan.unchanged_ids))
                        cursor = high
                except Exception as exc:
                    self._record_failure(run_id, exc)
                    raise
                batches += 1
            with session_scope(self._mssql) as session:
                run = MigrationStateRepository(session).get_run(run_id) or {}
        self._log("migrate", {"run_id": run_id, "resumed": resumed, "batches": batches, "state": run.get("state")})
        return run

    def _start_or_resume(self) -> tuple[int, int, bool]:
        with session_scope(self._mssql) as session:
            repo = MigrationStateRepository(session)
            repo.fail_stale(self._settings.migration_stale_seconds)
            existing = repo.get_resumable()
            if existing:
                repo.resume(existing["run_id"])
                return int(existing["run_id"]), int(existing["cursor_last_id"]), True
            return repo.create_run(), 0, False

    def _record_failure(self, run_id: int, exc: Exception) -> None:
        log.exception("Migration run %s failed", run_id)
        try:
            with session_scope(self._mssql) as session:
                MigrationStateRepository(session).mark_failed(run_id, f"{type(exc).__name__}: {exc}")
        except Exception:  # never mask the original error
            log.exception("Could not record failure of run %s", run_id)

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        """Session-scoped application lock held for the duration of the run."""
        session = Session(self._mssql)
        try:
            code = session.execute(
                # NOCOUNT suppresses "rows affected" messages so the only result set is the
                # SELECT below (sp_getapplock itself returns a status code, not a result set).
                text(
                    "SET NOCOUNT ON; "
                    "DECLARE @rc INT; "
                    "EXEC @rc = sp_getapplock @Resource = :res, @LockMode = 'Exclusive', "
                    "  @LockOwner = 'Session', @LockTimeout = 0; "
                    "SELECT @rc AS rc"
                ),
                {"res": LOCK_RESOURCE},
            ).scalar_one()
            if int(code) < 0:
                raise MigrationAlreadyRunning("A migration is already running")
            try:
                yield
            finally:
                session.execute(
                    text("EXEC sp_releaseapplock @Resource = :res, @LockOwner = 'Session'"),
                    {"res": LOCK_RESOURCE},
                )
        finally:
            session.commit()
            session.close()

    # -------------------------------------------------------------- publish
    def publish_pending(self, max_batches: int | None = None) -> PublishOutcome:
        """Move pending outbox rows into the PostgreSQL work queue."""
        batches = published = 0
        while max_batches is None or batches < max_batches:
            with session_scope(self._mssql) as source:
                repo = MigrationStateRepository(source)
                items = repo.pending_outbox(self._settings.publish_batch_size)
                if not items:
                    break
                with session_scope(self._postgres) as target:
                    WorkQueueRepository(target).enqueue(items)
                repo.mark_published([int(i["outbox_id"]) for i in items])
            batches += 1
            published += len(items)
        if published:
            self._log("publish", {"batches": batches, "published": published})
        return PublishOutcome(batches=batches, published=published)

    # ------------------------------------------------------------- simulate
    def simulate_source_activity(self, new_rows: int, changed_rows: int) -> tuple[int, int]:
        with session_scope(self._mssql) as session:
            inserted, updated = MigrationStateRepository(session).mutate_source(new_rows, changed_rows)
        self._log("simulate", {"inserted": inserted, "updated": updated})
        return inserted, updated

    # ----------------------------------------------------------------- misc
    def _log(self, event: str, detail: dict) -> None:
        """Best-effort audit trail in PostgreSQL; never fails the operation."""
        try:
            with session_scope(self._postgres) as session:
                SyncLogRepository(session).add("migration", event, detail)
        except Exception:
            log.warning("Could not write sync log for %s", event, exc_info=True)
