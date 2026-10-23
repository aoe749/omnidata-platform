"""PostgreSQL repositories: atomic counters, SKIP LOCKED work queue, analytics.

Postgres-specific features used on purpose:
  * ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING``   atomic counters / upserts
  * ``SELECT ... FOR UPDATE SKIP LOCKED``                contention-free work claiming
  * partial indexes, ``jsonb``, array parameters (``= ANY(:ids)``)
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Iterable, Iterator, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.query_builder import WhereBuilder, like_pattern, order_by


class LeaseLostError(RuntimeError):
    """The queue row is no longer leased to this worker (reset by the sweeper, or re-claimed)."""


# ------------------------------------------------------------------ counters
class SequenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def next_value(self, kind: str, period: str) -> int:
        """Allocate the next number for ``(kind, period)``.

        The statement creates the counter on first use and increments it
        otherwise, atomically. The row lock lives until the surrounding
        transaction ends, so allocating *inside the transaction that consumes
        the number* yields gap-free sequences: a rollback also rolls back the
        increment.
        """
        return int(
            self.session.execute(
                text(
                    "INSERT INTO sequence_counters (kind, period, last_value) VALUES (:kind, :period, 1) "
                    "ON CONFLICT (kind, period) DO UPDATE "
                    "SET last_value = sequence_counters.last_value + 1, updated_at = now() "
                    "RETURNING last_value"
                ),
                {"kind": kind, "period": period},
            ).scalar_one()
        )


# --------------------------------------------------------------- work queue
QUEUE_SORTABLE = {
    "id": "id",
    "source_id": "source_id",
    "status": "status",
    "attempts": "attempts",
    "available_at": "available_at",
    "created_at": "created_at",
}


class WorkQueueRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(self, items: Sequence[dict[str, Any]]) -> None:
        """Idempotent insert: ``(source_id, content_hash)`` duplicates are silently skipped."""
        if not items:
            return
        self.session.execute(
            text(
                "INSERT INTO work_queue (source_id, content_hash, payload, status) "
                "VALUES (:source_id, :content_hash, CAST(:payload AS jsonb), 'queued') "
                "ON CONFLICT (source_id, content_hash) DO NOTHING"
            ),
            [
                {"source_id": i["source_id"], "content_hash": i["content_hash"], "payload": i["payload"]}
                for i in items
            ],
        )

    def claim_batch(self, batch_size: int, worker_id: str) -> list[dict[str, Any]]:
        """Atomically lease up to ``batch_size`` queued rows.

        ``FOR UPDATE SKIP LOCKED`` makes concurrent workers pick *disjoint* rows
        without blocking each other; ``available_at`` implements retry back-off.
        """
        rows = self.session.execute(
            text(
                "WITH claimed AS ("
                "  SELECT id FROM work_queue"
                "  WHERE status = 'queued' AND available_at <= now()"
                "  ORDER BY id LIMIT :batch FOR UPDATE SKIP LOCKED"
                ") "
                "UPDATE work_queue w SET status = 'processing', attempts = w.attempts + 1, "
                "  locked_by = :worker, locked_at = now() "
                "FROM claimed WHERE w.id = claimed.id "
                "RETURNING w.id, w.source_id, w.content_hash, w.payload, w.attempts"
            ),
            {"batch": batch_size, "worker": worker_id},
        ).mappings()
        return sorted((dict(r) for r in rows), key=lambda r: r["id"])

    def mark_done(self, item_id: int, worker_id: str) -> None:
        result = self.session.execute(
            text(
                "UPDATE work_queue SET status = 'done', processed_at = now(), "
                "locked_by = NULL, locked_at = NULL, last_error = NULL "
                "WHERE id = :id AND status = 'processing' AND locked_by = :worker"
            ),
            {"id": item_id, "worker": worker_id},
        )
        if result.rowcount != 1:
            raise LeaseLostError(f"queue item {item_id} is no longer leased to {worker_id}")

    def mark_retry(self, item_id: int, error: str, max_attempts: int) -> str:
        """Record a failure. Returns the new status: 'queued' (back-off) or 'dead'."""
        return str(
            self.session.execute(
                text(
                    "UPDATE work_queue SET "
                    "  status = CASE WHEN attempts >= :max_attempts THEN 'dead' ELSE 'queued' END, "
                    "  available_at = now() + make_interval(secs => "
                    "      CAST(LEAST(300, 5 * power(2, attempts - 1)) AS double precision)), "
                    "  last_error = :error, locked_by = NULL, locked_at = NULL "
                    "WHERE id = :id AND status = 'processing' "
                    "RETURNING status"
                ),
                {"id": item_id, "error": error[:2000], "max_attempts": max_attempts},
            ).scalar_one_or_none()
            or "queued"
        )

    def reset_stale(self, stale_seconds: int) -> int:
        """Sweeper: rows leased longer than ``stale_seconds`` (crashed worker) go back to 'queued'."""
        return int(
            self.session.execute(
                text(
                    "UPDATE work_queue SET status = 'queued', locked_by = NULL, locked_at = NULL, "
                    "  last_error = 'reset: stale lease' "
                    "WHERE status = 'processing' "
                    "  AND locked_at < now() - make_interval(secs => CAST(:stale AS double precision))"
                ),
                {"stale": stale_seconds},
            ).rowcount
        )

    def counts_by_status(self) -> dict[str, int]:
        rows = self.session.execute(text("SELECT status, count(*) AS n FROM work_queue GROUP BY status"))
        counts = {"queued": 0, "processing": 0, "done": 0, "dead": 0}
        counts.update({str(r.status): int(r.n) for r in rows})
        return counts

    def page(
        self, *, status: str | None, search: str | None, offset: int, limit: int, sort_by: str | None, sort_dir: str
    ) -> tuple[int, list[dict[str, Any]]]:
        where = WhereBuilder()
        if status:
            where.add("status = :status", status=status)
        if search:
            where.add("CAST(source_id AS text) LIKE :search", search=like_pattern(search))
        order = order_by(sort_by, sort_dir, QUEUE_SORTABLE, default="id", tiebreak="id")
        total = self.session.execute(text(f"SELECT count(*) FROM work_queue {where.sql}"), where.params).scalar_one()
        rows = self.session.execute(
            text(
                "SELECT id, source_id, status, attempts, available_at, locked_by, last_error, created_at, processed_at "
                f"FROM work_queue {where.sql} ORDER BY {order} LIMIT :limit OFFSET :offset"
            ),
            {**where.params, "limit": limit, "offset": offset},
        ).mappings()
        return int(total), [dict(r) for r in rows]


# ------------------------------------------------------------- transactions
TRANSACTION_SORTABLE = {
    "ingest_no": "ingest_no",
    "source_id": "source_id",
    "account_ref": "account_ref",
    "amount_cents": "amount_cents",
    "currency": "currency",
    "status": "status",
    "occurred_at": "occurred_at",
    "ingested_at": "ingested_at",
}
_TX_COLUMNS = "ingest_no, source_id, account_ref, amount_cents, currency, status, occurred_at, ingested_at"


class TransactionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find_ingest_no(self, source_id: int) -> str | None:
        return self.session.execute(
            text("SELECT ingest_no FROM ingested_transactions WHERE source_id = :id"), {"id": source_id}
        ).scalar_one_or_none()

    def upsert(self, *, ingest_no: str, queue_id: int, payload: dict[str, Any], content_hash: str) -> None:
        """Insert or update by ``source_id``; a stale queue item can never overwrite a newer one."""
        self.session.execute(
            text(
                "INSERT INTO ingested_transactions "
                "  (ingest_no, source_id, content_hash, last_queue_id, account_ref, amount_cents, currency, status, occurred_at) "
                "VALUES (:ingest_no, :source_id, :content_hash, :queue_id, :account_ref, :amount_cents, :currency, :status, "
                "        CAST(:occurred_at AS timestamptz)) "
                "ON CONFLICT (source_id) DO UPDATE SET "
                "  content_hash = EXCLUDED.content_hash, last_queue_id = EXCLUDED.last_queue_id, "
                "  account_ref = EXCLUDED.account_ref, amount_cents = EXCLUDED.amount_cents, "
                "  currency = EXCLUDED.currency, status = EXCLUDED.status, occurred_at = EXCLUDED.occurred_at, "
                "  ingested_at = now() "
                "WHERE ingested_transactions.last_queue_id < EXCLUDED.last_queue_id"
            ),
            {
                "ingest_no": ingest_no,
                "queue_id": queue_id,
                "content_hash": content_hash,
                "source_id": payload["source_id"],
                "account_ref": payload["account_ref"],
                "amount_cents": payload["amount_cents"],
                "currency": payload["currency"],
                "status": payload["status"],
                "occurred_at": payload["occurred_at"],
            },
        )

    @staticmethod
    def _filters(
        search: str | None,
        currency: str | None,
        status: str | None,
        min_amount_cents: int | None,
        max_amount_cents: int | None,
        occurred_from: date | None,
        occurred_to: date | None,
    ) -> WhereBuilder:
        where = WhereBuilder()
        if search:
            where.add("(account_ref ILIKE :search OR ingest_no ILIKE :search)", search=like_pattern(search))
        if currency:
            where.add("currency = :currency", currency=currency.upper())
        if status:
            where.add("status = :status", status=status)
        if min_amount_cents is not None:
            where.add("amount_cents >= :min_amount", min_amount=min_amount_cents)
        if max_amount_cents is not None:
            where.add("amount_cents <= :max_amount", max_amount=max_amount_cents)
        if occurred_from:
            where.add("occurred_at >= CAST(:occurred_from AS date)", occurred_from=occurred_from)
        if occurred_to:  # inclusive end date
            where.add("occurred_at < CAST(:occurred_to AS date) + 1", occurred_to=occurred_to)
        return where

    def page(
        self,
        *,
        search: str | None,
        currency: str | None,
        status: str | None,
        min_amount_cents: int | None,
        max_amount_cents: int | None,
        occurred_from: date | None,
        occurred_to: date | None,
        offset: int,
        limit: int,
        sort_by: str | None,
        sort_dir: str,
    ) -> tuple[int, list[dict[str, Any]]]:
        where = self._filters(search, currency, status, min_amount_cents, max_amount_cents, occurred_from, occurred_to)
        order = order_by(sort_by, sort_dir, TRANSACTION_SORTABLE, default="occurred_at", tiebreak="ingest_no")
        total = self.session.execute(
            text(f"SELECT count(*) FROM ingested_transactions {where.sql}"), where.params
        ).scalar_one()
        rows = self.session.execute(
            text(
                f"SELECT {_TX_COLUMNS} FROM ingested_transactions {where.sql} "
                f"ORDER BY {order} LIMIT :limit OFFSET :offset"
            ),
            {**where.params, "limit": limit, "offset": offset},
        ).mappings()
        return int(total), [dict(r) for r in rows]

    def stream(
        self,
        *,
        search: str | None,
        currency: str | None,
        status: str | None,
        min_amount_cents: int | None,
        max_amount_cents: int | None,
        occurred_from: date | None,
        occurred_to: date | None,
        limit: int,
    ) -> Iterator[dict[str, Any]]:
        """Server-side cursor for exports (constant memory)."""
        where = self._filters(search, currency, status, min_amount_cents, max_amount_cents, occurred_from, occurred_to)
        result = self.session.connection().execution_options(stream_results=True, yield_per=1000).execute(
            text(
                f"SELECT {_TX_COLUMNS} FROM ingested_transactions {where.sql} "
                "ORDER BY occurred_at DESC, ingest_no LIMIT :limit"
            ),
            {**where.params, "limit": limit},
        )
        for row in result.mappings():
            yield dict(row)

    def count(self) -> int:
        return int(self.session.execute(text("SELECT count(*) FROM ingested_transactions")).scalar_one())


# ------------------------------------------------------------------ metrics
class MetricsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def refresh_days(self, days: Iterable[date]) -> None:
        """Rebuild the aggregate rows of the given days from the source of truth (settled only)."""
        day_list = sorted(set(days))
        if not day_list:
            return
        self.session.execute(text("DELETE FROM metrics_daily WHERE day = ANY(:days)"), {"days": day_list})
        self.session.execute(
            text(
                "INSERT INTO metrics_daily (day, currency, tx_count, total_cents) "
                "SELECT CAST(occurred_at AT TIME ZONE 'UTC' AS date), currency, count(*), "
                "       CAST(coalesce(sum(amount_cents), 0) AS bigint) "
                "FROM ingested_transactions "
                "WHERE status = 'settled' AND CAST(occurred_at AT TIME ZONE 'UTC' AS date) = ANY(:days) "
                "GROUP BY 1, 2 "
                "ON CONFLICT (day, currency) DO UPDATE SET "
                "  tx_count = EXCLUDED.tx_count, total_cents = EXCLUDED.total_cents, updated_at = now()"
            ),
            {"days": day_list},
        )

    def recent(self, days: int) -> list[dict[str, Any]]:
        rows = self.session.execute(
            text(
                "SELECT day, CAST(sum(tx_count) AS bigint) AS tx_count, CAST(sum(total_cents) AS bigint) AS total_cents "
                "FROM metrics_daily WHERE day >= current_date - CAST(:days AS integer) "
                "GROUP BY day ORDER BY day"
            ),
            {"days": days},
        ).mappings()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------- logs
class SyncLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, source: str, event: str, detail: dict[str, Any]) -> None:
        self.session.execute(
            text("INSERT INTO sync_logs (source, event, detail) VALUES (:source, :event, CAST(:detail AS jsonb))"),
            {"source": source, "event": event, "detail": json.dumps(detail, default=str)},
        )

    def recent(self, limit: int) -> list[dict[str, Any]]:
        rows = self.session.execute(
            text("SELECT id, source, event, detail, created_at FROM sync_logs ORDER BY id DESC LIMIT :limit"),
            {"limit": limit},
        ).mappings()
        return [dict(r) for r in rows]
