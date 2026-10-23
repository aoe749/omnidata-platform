"""Pydantic response/request models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ----------------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class UserProfile(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    permissions: dict[str, int]
    action_bits: dict[str, int]


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    profile: UserProfile


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


# ------------------------------------------------------------------ tables
class TransactionOut(BaseModel):
    ingest_no: str
    source_id: int
    account_ref: str
    amount_cents: int
    currency: str
    status: str
    occurred_at: datetime
    ingested_at: datetime


class QueueItemOut(BaseModel):
    id: int
    source_id: int
    status: str
    attempts: int
    available_at: datetime
    locked_by: str | None = None
    last_error: str | None = None
    created_at: datetime
    processed_at: datetime | None = None


class MigrationRunOut(BaseModel):
    run_id: int
    state: str
    cursor_last_id: int
    rows_scanned: int
    rows_new: int
    rows_changed: int
    rows_unchanged: int
    last_error: str | None = None
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


# --------------------------------------------------------------- operations
class MigrationRequest(BaseModel):
    max_batches: int | None = Field(default=None, ge=1, le=1000)


class PublishRequest(BaseModel):
    max_batches: int | None = Field(default=None, ge=1, le=1000)


class IngestionRequest(BaseModel):
    max_batches: int = Field(default=5, ge=1, le=100)


class SimulateRequest(BaseModel):
    new_rows: int = Field(default=25, ge=0, le=500)
    changed_rows: int = Field(default=25, ge=0, le=500)


class PublishResult(BaseModel):
    batches: int
    published: int


class IngestionResult(BaseModel):
    batches: int
    claimed: int
    done: int
    retried: int
    dead: int
    reset_stale: int


class SimulateResult(BaseModel):
    inserted: int
    updated: int


# --------------------------------------------------------------------- stats
class DbHealth(BaseModel):
    status: Literal["ok", "error"]
    error: str | None = None


class MssqlStats(DbHealth):
    source_rows: int = 0
    crosswalk_rows: int = 0
    outbox_pending: int = 0
    outbox_published: int = 0
    last_run: MigrationRunOut | None = None


class DailyMetric(BaseModel):
    day: date
    tx_count: int
    total_cents: int


class SyncLogOut(BaseModel):
    id: int
    source: str
    event: str
    detail: dict[str, Any]
    created_at: datetime


class PostgresStats(DbHealth):
    queue: dict[str, int] = Field(default_factory=dict)
    ingested_rows: int = 0
    daily_metrics: list[DailyMetric] = Field(default_factory=list)
    recent_logs: list[SyncLogOut] = Field(default_factory=list)


class MysqlStats(DbHealth):
    active_users: int = 0
    roles: int = 0


class Overview(BaseModel):
    mssql: MssqlStats
    postgres: PostgresStats
    mysql: MysqlStats
    generated_at: datetime
