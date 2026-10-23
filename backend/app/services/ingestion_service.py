"""Analytical ingestion worker logic (PostgreSQL).

Life-cycle of a queue item::

    queued --claim--> processing --ok--------------> done
                          |------fail, attempts left-> queued   (exponential back-off)
                          |------fail, out of attempts-> dead
                          '------lease expired (sweeper)-> queued

Claiming and processing use *separate* transactions: the claim commits quickly
(releasing row locks while the lease is recorded in ``locked_by``/``locked_at``),
and each item is then processed atomically together with its ``done`` mark.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.db.engines import DatabaseRegistry, session_scope
from app.repositories.postgres_repo import (
    LeaseLostError,
    MetricsRepository,
    SequenceRepository,
    SyncLogRepository,
    TransactionRepository,
    WorkQueueRepository,
)

log = logging.getLogger(__name__)


class TransactionPayload(BaseModel):
    """Validated shape of a queue payload; bad messages fail fast and end up 'dead'."""

    source_id: int
    account_ref: str = Field(min_length=1, max_length=32)
    amount_cents: int
    currency: str = Field(min_length=3, max_length=3)
    status: str
    occurred_at: datetime


@dataclass
class IngestionOutcome:
    batches: int = 0
    claimed: int = 0
    done: int = 0
    retried: int = 0
    dead: int = 0
    reset_stale: int = 0


class IngestionService:
    def __init__(self, registry: DatabaseRegistry, settings: Settings, worker_id: str | None = None) -> None:
        self._engine = registry.postgres
        self._settings = settings
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"

    def run(self, max_batches: int = 1) -> IngestionOutcome:
        outcome = IngestionOutcome()
        with session_scope(self._engine) as session:
            outcome.reset_stale = WorkQueueRepository(session).reset_stale(self._settings.worker_stale_seconds)

        for _ in range(max_batches):
            with session_scope(self._engine) as session:
                items = WorkQueueRepository(session).claim_batch(self._settings.worker_batch_size, self.worker_id)
            if not items:
                break
            outcome.batches += 1
            outcome.claimed += len(items)
            touched_days: set[date] = set()
            for item in items:
                day = self._process(item, outcome)
                if day:
                    touched_days.add(day)
            if touched_days:
                with session_scope(self._engine) as session:
                    MetricsRepository(session).refresh_days(touched_days)

        if outcome.claimed or outcome.reset_stale:
            self._log(outcome)
        return outcome

    # ------------------------------------------------------------------ item
    def _process(self, item: dict[str, Any], outcome: IngestionOutcome) -> date | None:
        try:
            payload = TransactionPayload.model_validate(item["payload"])
            with session_scope(self._engine) as session:
                day = self._ingest(session, item, payload)
                WorkQueueRepository(session).mark_done(item["id"], self.worker_id)
            outcome.done += 1
            return day
        except LeaseLostError:
            log.warning("Lease lost for queue item %s; another worker owns it now", item["id"])
        except Exception as exc:
            with session_scope(self._engine) as session:
                status = WorkQueueRepository(session).mark_retry(
                    item["id"], f"{type(exc).__name__}: {exc}", self._settings.worker_max_attempts
                )
            if status == "dead":
                outcome.dead += 1
                log.error("Queue item %s moved to dead letters: %s", item["id"], exc)
            else:
                outcome.retried += 1
        return None

    @staticmethod
    def _ingest(session: Any, item: dict[str, Any], payload: TransactionPayload) -> date:
        transactions = TransactionRepository(session)
        occurred_day = payload.occurred_at.date()
        ingest_no = transactions.find_ingest_no(payload.source_id)
        if ingest_no is None:
            # Allocated in the same transaction as the insert -> no gaps on rollback.
            period = occurred_day.strftime("%Y%m%d")
            number = SequenceRepository(session).next_value("ingest", period)
            ingest_no = f"TX-{period}-{number:06d}"
        transactions.upsert(
            ingest_no=ingest_no,
            queue_id=int(item["id"]),
            payload=payload.model_dump(mode="json"),
            content_hash=str(item["content_hash"]).strip(),
        )
        return occurred_day

    def _log(self, outcome: IngestionOutcome) -> None:
        try:
            with session_scope(self._engine) as session:
                SyncLogRepository(session).add(
                    "ingestion", "batch", {"worker": self.worker_id, **outcome.__dict__}
                )
        except Exception:
            log.warning("Could not write ingestion log", exc_info=True)
