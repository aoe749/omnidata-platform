-- PostgreSQL 16 — analytical ingestion schema.
-- Idempotent: executed by the official image on first start (docker-entrypoint-initdb.d)
-- and safe to re-run manually with psql.

-- Concurrent atomic counters. One row per (kind, period); the row lock taken by
-- INSERT ... ON CONFLICT DO UPDATE serialises allocators for that key only.
CREATE TABLE IF NOT EXISTS sequence_counters (
    kind        TEXT        NOT NULL,
    period      TEXT        NOT NULL,
    last_value  BIGINT      NOT NULL CHECK (last_value >= 0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, period)
);

-- Work queue consumed with SELECT ... FOR UPDATE SKIP LOCKED.
CREATE TABLE IF NOT EXISTS work_queue (
    id            BIGSERIAL   PRIMARY KEY,
    source_id     BIGINT      NOT NULL,
    content_hash  CHAR(64)    NOT NULL,
    payload       JSONB       NOT NULL,
    status        TEXT        NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'processing', 'done', 'dead')),
    attempts      INTEGER     NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_by     TEXT,
    locked_at     TIMESTAMPTZ,
    last_error    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at  TIMESTAMPTZ,
    -- Idempotent hand-off: re-publishing the same outbox row is a no-op.
    UNIQUE (source_id, content_hash)
);

-- Partial indexes keep the hot path tiny even when millions of 'done' rows accumulate.
CREATE INDEX IF NOT EXISTS ix_work_queue_claim
    ON work_queue (available_at, id) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS ix_work_queue_processing
    ON work_queue (locked_at) WHERE status = 'processing';
CREATE INDEX IF NOT EXISTS ix_work_queue_status_id
    ON work_queue (status, id DESC);

CREATE TABLE IF NOT EXISTS ingested_transactions (
    ingest_no      TEXT        PRIMARY KEY,
    source_id      BIGINT      NOT NULL UNIQUE,
    content_hash   CHAR(64)    NOT NULL,
    last_queue_id  BIGINT      NOT NULL,
    account_ref    TEXT        NOT NULL,
    amount_cents   BIGINT      NOT NULL,
    currency       CHAR(3)     NOT NULL,
    status         TEXT        NOT NULL,
    occurred_at    TIMESTAMPTZ NOT NULL,
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ingested_occurred ON ingested_transactions (occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_ingested_currency_status ON ingested_transactions (currency, status);

CREATE TABLE IF NOT EXISTS metrics_daily (
    day          DATE        NOT NULL,
    currency     CHAR(3)     NOT NULL,
    tx_count     BIGINT      NOT NULL,
    total_cents  BIGINT      NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (day, currency)
);

CREATE TABLE IF NOT EXISTS sync_logs (
    id          BIGSERIAL   PRIMARY KEY,
    source      TEXT        NOT NULL,
    event       TEXT        NOT NULL,
    detail      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_sync_logs_created ON sync_logs (created_at DESC);

-- LLM spend per tenant and calendar month (micro-USD). A reservation is booked
-- before a provider call and replaced by the real cost afterwards; the CHECKs
-- keep both counters non-negative even if a caller misbehaves.
CREATE TABLE IF NOT EXISTS llm_budget_usage (
    tenant_id        TEXT        NOT NULL,
    period           TEXT        NOT NULL,
    spent_micros     BIGINT      NOT NULL DEFAULT 0 CHECK (spent_micros >= 0),
    reserved_micros  BIGINT      NOT NULL DEFAULT 0 CHECK (reserved_micros >= 0),
    PRIMARY KEY (tenant_id, period)
);

-- Events accepted by the Node.js intake service. The primary key is the
-- sender's event id, so a redelivered webhook is a no-op.
CREATE TABLE IF NOT EXISTS inbound_events (
    event_id     TEXT        PRIMARY KEY,
    event_type   TEXT        NOT NULL,
    payload      JSONB       NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_inbound_events_received ON inbound_events (received_at DESC);
