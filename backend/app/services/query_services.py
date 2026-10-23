"""Read-side services: tables, CSV export, dashboard statistics, user admin."""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Callable, Iterator
from datetime import date, datetime, timezone
from typing import Any, TypeVar

from app.db.engines import DatabaseRegistry, session_scope
from app.repositories.mssql_repo import MigrationStateRepository
from app.repositories.mysql_repo import UserRepository
from app.repositories.postgres_repo import (
    MetricsRepository,
    SyncLogRepository,
    TransactionRepository,
    WorkQueueRepository,
)
from app.schemas.common import Page, TableParams
from app.schemas.models import (
    DailyMetric,
    MigrationRunOut,
    MssqlStats,
    MysqlStats,
    Overview,
    PostgresStats,
    QueueItemOut,
    SyncLogOut,
    TransactionOut,
    UserOut,
)

log = logging.getLogger(__name__)
T = TypeVar("T")

EXPORT_ROW_LIMIT = 100_000
CSV_COLUMNS = ["ingest_no", "source_id", "account_ref", "amount_cents", "currency", "status", "occurred_at", "ingested_at"]


class TransactionFilters:
    """Query-string filters shared by the table and the CSV export."""

    def __init__(
        self,
        search: str | None = None,
        currency: str | None = None,
        status: str | None = None,
        min_amount_cents: int | None = None,
        max_amount_cents: int | None = None,
        occurred_from: date | None = None,
        occurred_to: date | None = None,
    ) -> None:
        self.kwargs = {
            "search": search,
            "currency": currency,
            "status": status,
            "min_amount_cents": min_amount_cents,
            "max_amount_cents": max_amount_cents,
            "occurred_from": occurred_from,
            "occurred_to": occurred_to,
        }


class QueryService:
    def __init__(self, registry: DatabaseRegistry) -> None:
        self._registry = registry

    # --------------------------------------------------------------- tables
    def transactions(self, filters: TransactionFilters, params: TableParams) -> Page[TransactionOut]:
        with session_scope(self._registry.postgres) as session:
            total, rows = TransactionRepository(session).page(
                **filters.kwargs,
                offset=params.offset,
                limit=params.page_size,
                sort_by=params.sort_by,
                sort_dir=params.sort_dir,
            )
        return Page(items=[TransactionOut(**r) for r in rows], total=total, page=params.page, page_size=params.page_size)

    def export_transactions_csv(self, filters: TransactionFilters) -> Iterator[str]:
        """Yield CSV text chunks without materialising the result set."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(CSV_COLUMNS)
        with session_scope(self._registry.postgres) as session:
            for count, row in enumerate(
                TransactionRepository(session).stream(**filters.kwargs, limit=EXPORT_ROW_LIMIT), start=1
            ):
                writer.writerow([_csv_safe(row[c]) for c in CSV_COLUMNS])
                if count % 500 == 0:
                    yield buffer.getvalue()
                    buffer.seek(0)
                    buffer.truncate(0)
            yield buffer.getvalue()

    def queue(
        self, status: str | None, search: str | None, params: TableParams
    ) -> Page[QueueItemOut]:
        with session_scope(self._registry.postgres) as session:
            total, rows = WorkQueueRepository(session).page(
                status=status,
                search=search,
                offset=params.offset,
                limit=params.page_size,
                sort_by=params.sort_by,
                sort_dir=params.sort_dir,
            )
        return Page(items=[QueueItemOut(**r) for r in rows], total=total, page=params.page, page_size=params.page_size)

    def runs(self, state: str | None, params: TableParams) -> Page[MigrationRunOut]:
        with session_scope(self._registry.mssql) as session:
            total, rows = MigrationStateRepository(session).page_runs(
                state=state,
                offset=params.offset,
                limit=params.page_size,
                sort_by=params.sort_by,
                sort_dir=params.sort_dir,
            )
        return Page(items=[MigrationRunOut(**r) for r in rows], total=total, page=params.page, page_size=params.page_size)

    # ---------------------------------------------------------------- users
    def users(self) -> list[UserOut]:
        with session_scope(self._registry.mysql) as session:
            return [UserOut(**r) for r in UserRepository(session).list_users()]

    def deactivate_user(self, user_id: int) -> bool:
        with session_scope(self._registry.mysql) as session:
            return UserRepository(session).deactivate(user_id)

    # ------------------------------------------------------------ dashboard
    def overview(self) -> Overview:
        """Cross-database statistics. One unreachable database degrades only its own card."""
        return Overview(
            mssql=self._guard(self._mssql_stats, MssqlStats),
            postgres=self._guard(self._postgres_stats, PostgresStats),
            mysql=self._guard(self._mysql_stats, MysqlStats),
            generated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _guard(fn: Callable[[], T], model: type[T]) -> T:
        try:
            return fn()
        except Exception as exc:
            log.warning("Stats query failed for %s", model.__name__, exc_info=True)
            return model(status="error", error=type(exc).__name__)  # type: ignore[call-arg]

    def _mssql_stats(self) -> MssqlStats:
        with session_scope(self._registry.mssql) as session:
            repo = MigrationStateRepository(session)
            last = repo.latest_run()
            return MssqlStats(status="ok", **repo.counts(), last_run=MigrationRunOut(**last) if last else None)

    def _postgres_stats(self) -> PostgresStats:
        with session_scope(self._registry.postgres) as session:
            return PostgresStats(
                status="ok",
                queue=WorkQueueRepository(session).counts_by_status(),
                ingested_rows=TransactionRepository(session).count(),
                daily_metrics=[DailyMetric(**r) for r in MetricsRepository(session).recent(30)],
                recent_logs=[SyncLogOut(**r) for r in SyncLogRepository(session).recent(8)],
            )

    def _mysql_stats(self) -> MysqlStats:
        with session_scope(self._registry.mysql) as session:
            return MysqlStats(status="ok", **UserRepository(session).counts())


def _csv_safe(value: Any) -> Any:
    """Neutralise spreadsheet formula injection in text cells."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value
