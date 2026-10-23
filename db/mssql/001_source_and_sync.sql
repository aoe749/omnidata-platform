/*
 * MS SQL Server — source data + three-layer sync state.
 *
 * Idempotent: safe to run any number of times (every object is guarded).
 * Run with:  sqlcmd -C -I -b -S <host> -U sa -P <password> -i 001_source_and_sync.sql
 *            (-I enables QUOTED_IDENTIFIER, required for indexed/constrained objects)
 *
 * Layers used by the resumable migration service:
 *   1. sync.migration_runs  - durable checkpoint (cursor) per run  -> resumability
 *   2. sync.crosswalk       - source_id -> last seen content hash  -> change detection
 *   3. sync.outbox          - classified rows ready for publication -> hand-off to PostgreSQL
 */
IF DB_ID(N'omnidata_source') IS NULL
    CREATE DATABASE omnidata_source;
GO

USE omnidata_source;
GO

IF SCHEMA_ID(N'sync') IS NULL
    EXEC(N'CREATE SCHEMA sync');
GO

/* ---------------------------------------------------------------- source data */
IF OBJECT_ID(N'dbo.source_transactions', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.source_transactions (
        id           BIGINT IDENTITY(1, 1) NOT NULL,
        account_ref  NVARCHAR(32)  NOT NULL,
        amount_cents BIGINT        NOT NULL,
        currency     CHAR(3)       NOT NULL,
        status       NVARCHAR(16)  NOT NULL,
        occurred_at  DATETIME2(0)  NOT NULL,
        updated_at   DATETIME2(0)  NOT NULL CONSTRAINT df_source_transactions_updated DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_source_transactions PRIMARY KEY CLUSTERED (id),
        CONSTRAINT ck_source_transactions_status CHECK (status IN ('pending', 'settled', 'reversed'))
    );
END
GO

/* Deterministic mock data: 1000 rows across 250 accounts, 3 currencies, ~25 days. */
IF NOT EXISTS (SELECT 1 FROM dbo.source_transactions)
BEGIN
    ;WITH n AS (
        SELECT TOP (1000) CAST(ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS INT) AS i
        FROM sys.all_objects AS a CROSS JOIN sys.all_objects AS b
    )
    INSERT INTO dbo.source_transactions (account_ref, amount_cents, currency, status, occurred_at)
    SELECT CONCAT('ACC-', RIGHT(CONCAT('0000', 1 + (i * 7) % 250), 4)),
           CAST(((i * 7919) % 99000) + 100 AS BIGINT),
           CHOOSE(1 + i % 3, 'USD', 'EUR', 'GBP'),
           CHOOSE(1 + i % 4, 'settled', 'settled', 'pending', 'reversed'),
           DATEADD(MINUTE, -i * 37, CAST(SYSUTCDATETIME() AS DATETIME2(0)))
    FROM n;
END
GO

/* ------------------------------------------------- layer 1: durable checkpoints */
IF OBJECT_ID(N'sync.migration_runs', N'U') IS NULL
BEGIN
    CREATE TABLE sync.migration_runs (
        run_id         INT IDENTITY(1, 1) NOT NULL,
        state          NVARCHAR(16)  NOT NULL,
        cursor_last_id BIGINT        NOT NULL CONSTRAINT df_migration_runs_cursor DEFAULT 0,
        rows_scanned   INT           NOT NULL CONSTRAINT df_migration_runs_scanned DEFAULT 0,
        rows_new       INT           NOT NULL CONSTRAINT df_migration_runs_new DEFAULT 0,
        rows_changed   INT           NOT NULL CONSTRAINT df_migration_runs_changed DEFAULT 0,
        rows_unchanged INT           NOT NULL CONSTRAINT df_migration_runs_unchanged DEFAULT 0,
        last_error     NVARCHAR(1000) NULL,
        started_at     DATETIME2(0)  NOT NULL CONSTRAINT df_migration_runs_started DEFAULT SYSUTCDATETIME(),
        updated_at     DATETIME2(0)  NOT NULL CONSTRAINT df_migration_runs_updated DEFAULT SYSUTCDATETIME(),
        finished_at    DATETIME2(0)  NULL,
        CONSTRAINT pk_migration_runs PRIMARY KEY CLUSTERED (run_id),
        CONSTRAINT ck_migration_runs_state CHECK (state IN ('running', 'completed', 'failed'))
    );
END
GO

/* ------------------------------------------ layer 2: crosswalk (change detection) */
IF OBJECT_ID(N'sync.crosswalk', N'U') IS NULL
BEGIN
    CREATE TABLE sync.crosswalk (
        source_id      BIGINT       NOT NULL,
        content_hash   CHAR(64)     NOT NULL,
        first_seen_run INT          NOT NULL,
        last_seen_run  INT          NOT NULL,
        updated_at     DATETIME2(0) NOT NULL CONSTRAINT df_crosswalk_updated DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_crosswalk PRIMARY KEY CLUSTERED (source_id)
    );
END
GO

/* ------------------------------------- layer 3: outbox (classified, sync-ready) */
IF OBJECT_ID(N'sync.outbox', N'U') IS NULL
BEGIN
    CREATE TABLE sync.outbox (
        outbox_id      BIGINT IDENTITY(1, 1) NOT NULL,
        run_id         INT           NOT NULL,
        source_id      BIGINT        NOT NULL,
        classification NVARCHAR(16)  NOT NULL,
        content_hash   CHAR(64)      NOT NULL,
        payload        NVARCHAR(MAX) NOT NULL,
        state          NVARCHAR(16)  NOT NULL CONSTRAINT df_outbox_state DEFAULT 'pending',
        created_at     DATETIME2(0)  NOT NULL CONSTRAINT df_outbox_created DEFAULT SYSUTCDATETIME(),
        published_at   DATETIME2(0)  NULL,
        CONSTRAINT pk_outbox PRIMARY KEY CLUSTERED (outbox_id),
        CONSTRAINT uq_outbox_source_hash UNIQUE (source_id, content_hash),
        CONSTRAINT ck_outbox_classification CHECK (classification IN ('new', 'changed')),
        CONSTRAINT ck_outbox_state CHECK (state IN ('pending', 'published'))
    );
END
GO

/* Publisher scans pending rows in key order; READPAST lets concurrent publishers skip locked rows. */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_outbox_state' AND object_id = OBJECT_ID(N'sync.outbox'))
    CREATE INDEX ix_outbox_state ON sync.outbox (state, outbox_id) INCLUDE (source_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_migration_runs_state' AND object_id = OBJECT_ID(N'sync.migration_runs'))
    CREATE INDEX ix_migration_runs_state ON sync.migration_runs (state, run_id DESC);
GO
