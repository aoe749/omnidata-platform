/** API contract shared by the stores, pages and tables. Mirrors backend `app/schemas`. */

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type SortDir = "asc" | "desc";

/** What a server-side table asks for. `filters` holds only non-empty values. */
export interface TableQuery {
  page: number;
  page_size: number;
  sort_by?: string;
  sort_dir: SortDir;
  filters: Record<string, string>;
}

export type ActionName = "read" | "create" | "update" | "delete" | "export";
export type ResourceName = "users" | "transactions" | "sync" | "metrics";

export interface UserProfile {
  id: number;
  email: string;
  full_name: string;
  role: string;
  permissions: Record<string, number>;
  action_bits: Record<ActionName, number>;
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  profile: UserProfile;
}

export interface Transaction {
  ingest_no: string;
  source_id: number;
  account_ref: string;
  amount_cents: number;
  currency: string;
  status: string;
  occurred_at: string;
  ingested_at: string;
}

export interface QueueItem {
  id: number;
  source_id: number;
  status: "queued" | "processing" | "done" | "dead";
  attempts: number;
  available_at: string;
  locked_by: string | null;
  last_error: string | null;
  created_at: string;
  processed_at: string | null;
}

export interface MigrationRun {
  run_id: number;
  state: "running" | "completed" | "failed";
  cursor_last_id: number;
  rows_scanned: number;
  rows_new: number;
  rows_changed: number;
  rows_unchanged: number;
  last_error: string | null;
  started_at: string;
  updated_at: string;
  finished_at: string | null;
}

interface DbHealth {
  status: "ok" | "error";
  error: string | null;
}

export interface MssqlStats extends DbHealth {
  source_rows: number;
  crosswalk_rows: number;
  outbox_pending: number;
  outbox_published: number;
  last_run: MigrationRun | null;
}

export interface DailyMetric {
  day: string;
  tx_count: number;
  total_cents: number;
}

export interface SyncLog {
  id: number;
  source: string;
  event: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface PostgresStats extends DbHealth {
  queue: Record<"queued" | "processing" | "done" | "dead", number>;
  ingested_rows: number;
  daily_metrics: DailyMetric[];
  recent_logs: SyncLog[];
}

export interface MysqlStats extends DbHealth {
  active_users: number;
  roles: number;
}

export interface Overview {
  mssql: MssqlStats;
  postgres: PostgresStats;
  mysql: MysqlStats;
  generated_at: string;
}

export interface PublishResult {
  batches: number;
  published: number;
}

export interface IngestionResult {
  batches: number;
  claimed: number;
  done: number;
  retried: number;
  dead: number;
  reset_stale: number;
}

export interface SimulateResult {
  inserted: number;
  updated: number;
}
