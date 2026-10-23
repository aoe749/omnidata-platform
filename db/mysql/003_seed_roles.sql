-- Seed roles and their permission bitmasks (idempotent upserts).
-- Bits: read=1, create=2, update=4, delete=8, export=16.

INSERT INTO roles (name, description) VALUES
    ('admin',    'Full access to every resource'),
    ('operator', 'Runs synchronisation jobs and reads data'),
    ('analyst',  'Reads and exports analytical data'),
    ('viewer',   'Read-only access')
ON DUPLICATE KEY UPDATE description = VALUES(description);

INSERT INTO role_permissions (role_id, resource, mask)
SELECT r.id, p.resource, p.mask
  FROM roles r
  JOIN (
        SELECT 'admin' AS role_name, 'users'        AS resource, 1 | 2 | 4 | 8 | 16 AS mask
  UNION ALL SELECT 'admin',    'transactions', 1 | 2 | 4 | 8 | 16
  UNION ALL SELECT 'admin',    'sync',         1 | 2 | 4 | 8 | 16
  UNION ALL SELECT 'admin',    'metrics',      1 | 2 | 4 | 8 | 16
  UNION ALL SELECT 'operator', 'transactions', 1
  UNION ALL SELECT 'operator', 'sync',         1 | 2 | 4
  UNION ALL SELECT 'operator', 'metrics',      1
  UNION ALL SELECT 'analyst',  'transactions', 1 | 16
  UNION ALL SELECT 'analyst',  'sync',         1
  UNION ALL SELECT 'analyst',  'metrics',      1 | 16
  UNION ALL SELECT 'viewer',   'transactions', 1
  UNION ALL SELECT 'viewer',   'sync',         1
  UNION ALL SELECT 'viewer',   'metrics',      1
       ) p ON p.role_name = r.name
ON DUPLICATE KEY UPDATE mask = VALUES(mask);

INSERT IGNORE INTO schema_migrations (version) VALUES ('003_seed_roles');
