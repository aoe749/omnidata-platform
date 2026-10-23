"""MS SQL Server repositories: the mock source system and the three-layer sync state.

Layers (see db/mssql/001_source_and_sync.sql):
  1. ``sync.migration_runs``  durable checkpoint / cursor
  2. ``sync.crosswalk``       last-seen content hash per source row
  3. ``sync.outbox``          classified rows waiting to be published

Every method runs inside the caller's transaction; the *service* decides where
transactions begin and end.
"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.repositories.query_builder import WhereBuilder, order_by

RUN_SORTABLE = {
    "run_id": "run_id",
    "state": "state",
    "rows_scanned": "rows_scanned",
    "started_at": "started_at",
    "updated_at": "updated_at",
}


class MigrationStateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ----------------------------------------------------------- source data
    def fetch_source_after(self, after_id: int, limit: int) -> list[dict[str, Any]]:
        rows = self.session.execute(
            text(
                "SELECT TOP (:limit) id, account_ref, amount_cents, currency, status, occurred_at "
                "FROM dbo.source_transactions WHERE id > :after ORDER BY id"
            ),
            {"limit": limit, "after": after_id},
        ).mappings()
        return [dict(r) for r in rows]

    def mutate_source(self, new_rows: int, changed_rows: int) -> tuple[int, int]:
        """Simulate upstream activity: insert fresh rows and flip the status of random ones."""
        inserted = updated = 0
        if new_rows:
            inserted = self.session.execute(
                text(
                    "INSERT INTO dbo.source_transactions (account_ref, amount_cents, currency, status, occurred_at) "
                    "SELECT TOP (:n) "
                    "  CONCAT('ACC-', RIGHT(CONCAT('0000', ABS(CHECKSUM(NEWID())) % 250 + 1), 4)), "
                    "  CAST(ABS(CHECKSUM(NEWID())) % 99000 + 100 AS BIGINT), "
                    "  CHOOSE(ABS(CHECKSUM(NEWID())) % 3 + 1, 'USD', 'EUR', 'GBP'), "
                    "  'pending', CAST(SYSUTCDATETIME() AS DATETIME2(0)) "
                    "FROM sys.all_objects"
                ),
                {"n": new_rows},
            ).rowcount
        if changed_rows:
            updated = self.session.execute(
                text(
                    "WITH picked AS (SELECT TOP (:n) * FROM dbo.source_transactions ORDER BY NEWID()) "
                    "UPDATE picked SET status = CASE status WHEN 'pending' THEN 'settled' ELSE 'pending' END, "
                    "updated_at = SYSUTCDATETIME()"
                ),
                {"n": changed_rows},
            ).rowcount
        return int(inserted), int(updated)

    # --------------------------------------------------- layer 1: checkpoints
    def create_run(self) -> int:
        return int(
            self.session.execute(
                text("INSERT INTO sync.migration_runs (state) OUTPUT inserted.run_id VALUES ('running')")
            ).scalar_one()
        )

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        row = self.session.execute(
            text("SELECT * FROM sync.migration_runs WHERE run_id = :id"), {"id": run_id}
        ).mappings().first()
        return dict(row) if row else None

    def latest_run(self) -> dict[str, Any] | None:
        row = self.session.execute(
            text("SELECT TOP 1 * FROM sync.migration_runs ORDER BY run_id DESC")
        ).mappings().first()
        return dict(row) if row else None

    def get_resumable(self) -> dict[str, Any] | None:
        """Newest run that did not complete (still 'running' after a crash, or 'failed')."""
        row = self.session.execute(
            text(
                "SELECT TOP 1 run_id, state, cursor_last_id FROM sync.migration_runs "
                "WHERE state IN ('running', 'failed') ORDER BY run_id DESC"
            )
        ).mappings().first()
        return dict(row) if row else None

    def resume(self, run_id: int) -> None:
        self.session.execute(
            text(
                "UPDATE sync.migration_runs SET state = 'running', last_error = NULL, "
                "finished_at = NULL, updated_at = SYSUTCDATETIME() WHERE run_id = :id"
            ),
            {"id": run_id},
        )

    def advance(self, run_id: int, cursor: int, new: int, changed: int, unchanged: int) -> None:
        """Persist progress. Called inside the same transaction as the batch's data changes."""
        self.session.execute(
            text(
                "UPDATE sync.migration_runs SET cursor_last_id = :cursor, "
                "rows_scanned = rows_scanned + :scanned, rows_new = rows_new + :new, "
                "rows_changed = rows_changed + :changed, rows_unchanged = rows_unchanged + :unchanged, "
                "updated_at = SYSUTCDATETIME() WHERE run_id = :id"
            ),
            {
                "id": run_id,
                "cursor": cursor,
                "scanned": new + changed + unchanged,
                "new": new,
                "changed": changed,
                "unchanged": unchanged,
            },
        )

    def mark_completed(self, run_id: int) -> None:
        self.session.execute(
            text(
                "UPDATE sync.migration_runs SET state = 'completed', "
                "finished_at = SYSUTCDATETIME(), updated_at = SYSUTCDATETIME() WHERE run_id = :id"
            ),
            {"id": run_id},
        )

    def mark_failed(self, run_id: int, error: str) -> None:
        self.session.execute(
            text(
                "UPDATE sync.migration_runs SET state = 'failed', last_error = :error, "
                "updated_at = SYSUTCDATETIME() WHERE run_id = :id"
            ),
            {"id": run_id, "error": error[:1000]},
        )

    def fail_stale(self, stale_seconds: int) -> int:
        """Sweeper: a run stuck in 'running' without progress is marked 'failed' (then resumable)."""
        return int(
            self.session.execute(
                text(
                    "UPDATE sync.migration_runs SET state = 'failed', "
                    "last_error = 'stale: no progress heartbeat', updated_at = SYSUTCDATETIME() "
                    "WHERE state = 'running' AND updated_at < DATEADD(SECOND, -:stale, SYSUTCDATETIME())"
                ),
                {"stale": stale_seconds},
            ).rowcount
        )

    # ------------------------------------------------ layer 2: crosswalk
    def known_hashes(self, low_exclusive: int, high_inclusive: int) -> dict[int, str]:
        rows = self.session.execute(
            text(
                "SELECT source_id, content_hash FROM sync.crosswalk "
                "WHERE source_id > :low AND source_id <= :high"
            ),
            {"low": low_exclusive, "high": high_inclusive},
        )
        return {int(r.source_id): str(r.content_hash).strip() for r in rows}

    def upsert_crosswalk(
        self,
        run_id: int,
        new: Sequence[dict[str, Any]],
        changed: Sequence[dict[str, Any]],
        unchanged_ids: Sequence[int],
    ) -> None:
        if new:
            self.session.execute(
                text(
                    "INSERT INTO sync.crosswalk (source_id, content_hash, first_seen_run, last_seen_run) "
                    "VALUES (:source_id, :content_hash, :run_id, :run_id)"
                ),
                [{"source_id": e["source_id"], "content_hash": e["content_hash"], "run_id": run_id} for e in new],
            )
        if changed:
            self.session.execute(
                text(
                    "UPDATE sync.crosswalk SET content_hash = :content_hash, last_seen_run = :run_id, "
                    "updated_at = SYSUTCDATETIME() WHERE source_id = :source_id"
                ),
                [{"source_id": e["source_id"], "content_hash": e["content_hash"], "run_id": run_id} for e in changed],
            )
        if unchanged_ids:
            self.session.execute(
                text(
                    "UPDATE sync.crosswalk SET last_seen_run = :run_id WHERE source_id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"run_id": run_id, "ids": list(unchanged_ids)},
            )

    # ------------------------------------------------ layer 3: outbox
    def insert_outbox(self, run_id: int, entries: Sequence[dict[str, Any]]) -> None:
        if not entries:
            return
        self.session.execute(
            text(
                "INSERT INTO sync.outbox (run_id, source_id, classification, content_hash, payload, state) "
                "VALUES (:run_id, :source_id, :classification, :content_hash, :payload, 'pending')"
            ),
            [
                {
                    "run_id": run_id,
                    "source_id": e["source_id"],
                    "classification": e["classification"],
                    "content_hash": e["content_hash"],
                    "payload": e["payload"],
                }
                for e in entries
            ],
        )

    def pending_outbox(self, limit: int) -> list[dict[str, Any]]:
        """Lock a batch of pending rows. READPAST lets concurrent publishers skip locked rows."""
        rows = self.session.execute(
            text(
                "SELECT TOP (:limit) outbox_id, source_id, content_hash, payload "
                "FROM sync.outbox WITH (UPDLOCK, READPAST, ROWLOCK) "
                "WHERE state = 'pending' ORDER BY outbox_id"
            ),
            {"limit": limit},
        ).mappings()
        return [dict(r) for r in rows]

    def mark_published(self, outbox_ids: Sequence[int]) -> None:
        if not outbox_ids:
            return
        self.session.execute(
            text(
                "UPDATE sync.outbox SET state = 'published', published_at = SYSUTCDATETIME() "
                "WHERE outbox_id IN :ids AND state = 'pending'"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": list(outbox_ids)},
        )

    # ------------------------------------------------------ reads for the API
    def page_runs(
        self, *, state: str | None, offset: int, limit: int, sort_by: str | None, sort_dir: str
    ) -> tuple[int, list[dict[str, Any]]]:
        where = WhereBuilder()
        if state:
            where.add("state = :state", state=state)
        order = order_by(sort_by, sort_dir, RUN_SORTABLE, default="run_id", tiebreak="run_id")
        total = self.session.execute(
            text(f"SELECT COUNT(*) FROM sync.migration_runs {where.sql}"), where.params
        ).scalar_one()
        # `where.sql` / `order` contain only allow-listed fragments; values are bound.
        rows = self.session.execute(
            text(
                f"SELECT * FROM sync.migration_runs {where.sql} ORDER BY {order} "
                "OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY"
            ),
            {**where.params, "offset": offset, "limit": limit},
        ).mappings()
        return int(total), [dict(r) for r in rows]

    def counts(self) -> dict[str, int]:
        row = self.session.execute(
            text(
                "SELECT "
                " (SELECT COUNT_BIG(*) FROM dbo.source_transactions) AS source_rows, "
                " (SELECT COUNT_BIG(*) FROM sync.crosswalk) AS crosswalk_rows, "
                " (SELECT COUNT_BIG(*) FROM sync.outbox WHERE state = 'pending') AS outbox_pending, "
                " (SELECT COUNT_BIG(*) FROM sync.outbox WHERE state = 'published') AS outbox_published"
            )
        ).mappings().one()
        return {k: int(v) for k, v in row.items()}
