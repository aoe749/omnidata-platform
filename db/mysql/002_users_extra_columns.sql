-- Idempotent schema evolution without stored procedures.
--
-- MySQL has no "ADD COLUMN IF NOT EXISTS" / "CREATE INDEX IF NOT EXISTS".
-- The pattern below asks information_schema whether the change is already
-- applied, builds the DDL as a string only when it is not, and runs it through
-- a prepared statement. Re-running this file is a no-op.

-- 1) users.last_login_at --------------------------------------------------------
SET @ddl = IF(
    (SELECT COUNT(*)
       FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME   = 'users'
        AND COLUMN_NAME  = 'last_login_at') = 0,
    'ALTER TABLE users ADD COLUMN last_login_at DATETIME NULL AFTER created_at',
    'SELECT ''users.last_login_at already present'' AS info'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 2) users.failed_logins --------------------------------------------------------
SET @ddl = IF(
    (SELECT COUNT(*)
       FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME   = 'users'
        AND COLUMN_NAME  = 'failed_logins') = 0,
    'ALTER TABLE users ADD COLUMN failed_logins SMALLINT UNSIGNED NOT NULL DEFAULT 0',
    'SELECT ''users.failed_logins already present'' AS info'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 3) index on (is_active, created_at) ------------------------------------------
SET @ddl = IF(
    (SELECT COUNT(*)
       FROM information_schema.STATISTICS
      WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME   = 'users'
        AND INDEX_NAME   = 'ix_users_active_created') = 0,
    'CREATE INDEX ix_users_active_created ON users (is_active, created_at)',
    'SELECT ''ix_users_active_created already present'' AS info'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

INSERT IGNORE INTO schema_migrations (version) VALUES ('002_users_extra_columns');
