import { useEffect, useMemo } from "react";

import { BarChart, DbCard, Stat, StatusBadge } from "../components/widgets";
import { formatDateTime, formatNumber } from "../lib/format";
import { useAuthStore } from "../store/auth";
import { useSyncStore, type SyncAction } from "../store/sync";

const POLL_MS = 10_000;

const ACTIONS: { id: SyncAction; label: string; description: string; resource: "sync"; action: "create" | "update" }[] = [
  { id: "simulate", label: "1 · Simulate source changes", description: "Insert and modify rows in MS SQL", resource: "sync", action: "update" },
  { id: "migrate", label: "2 · Run migration", description: "Resume or start a run; classify rows", resource: "sync", action: "create" },
  { id: "publish", label: "3 · Publish outbox", description: "MS SQL outbox → PostgreSQL queue", resource: "sync", action: "update" },
  { id: "ingest", label: "4 · Process queue", description: "Claim with SKIP LOCKED and ingest", resource: "sync", action: "update" },
];

export function DashboardPage() {
  const { overview, loading, busy, error, notice, refresh, clearMessages, ...ops } = useSyncStore();
  const can = useAuthStore((s) => s.can);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh({ silent: true }), POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const chart = useMemo(
    () => (overview?.postgres.daily_metrics ?? []).map((m) => ({ label: m.day, value: m.tx_count })),
    [overview],
  );
  const settledCount = useMemo(() => chart.reduce((sum, d) => sum + d.value, 0), [chart]);

  const ms = overview?.mssql;
  const pg = overview?.postgres;
  const my = overview?.mysql;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Synchronisation overview</h1>
          <p className="muted">
            {overview ? `Updated ${formatDateTime(overview.generated_at)}` : loading ? "Loading…" : "No data"}
          </p>
        </div>
        <button type="button" className="btn" onClick={() => void refresh()} disabled={loading}>
          Refresh
        </button>
      </div>

      {error && (
        <div role="alert" className="banner banner-error" onClick={clearMessages}>
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="banner banner-ok" onClick={clearMessages}>
          {notice}
        </div>
      )}

      <section className="grid-3" aria-label="Databases">
        <DbCard title="Source & migration state" engine="MS SQL Server" status={ms?.status ?? "unknown"} error={ms?.error}>
          <Stat label="Source rows" value={ms?.source_rows ?? 0} />
          <Stat label="Crosswalk" value={ms?.crosswalk_rows ?? 0} hint="rows with a known hash" />
          <Stat label="Outbox pending" value={ms?.outbox_pending ?? 0} />
          <Stat label="Outbox published" value={ms?.outbox_published ?? 0} />
          {ms?.last_run && (
            <div className="stat stat-wide">
              <dt>Last run</dt>
              <dd>
                #{ms.last_run.run_id} <StatusBadge value={ms.last_run.state} />
              </dd>
              <small>
                +{ms.last_run.rows_new} new · ~{ms.last_run.rows_changed} changed · ={ms.last_run.rows_unchanged} same
              </small>
            </div>
          )}
        </DbCard>

        <DbCard title="Analytical ingestion" engine="PostgreSQL 16" status={pg?.status ?? "unknown"} error={pg?.error}>
          <Stat label="Queued" value={pg?.queue.queued ?? 0} />
          <Stat label="Processing" value={pg?.queue.processing ?? 0} />
          <Stat label="Done" value={pg?.queue.done ?? 0} />
          <Stat label="Dead letters" value={pg?.queue.dead ?? 0} />
          <Stat label="Ingested rows" value={pg?.ingested_rows ?? 0} />
        </DbCard>

        <DbCard title="Access control" engine="MySQL 8" status={my?.status ?? "unknown"} error={my?.error}>
          <Stat label="Active users" value={my?.active_users ?? 0} />
          <Stat label="Roles" value={my?.roles ?? 0} />
          <Stat label="Permission model" value="Bitmask" hint="read · create · update · delete · export" />
        </DbCard>
      </section>

      <section className="card pipeline" aria-label="Pipeline controls">
        <h2>Pipeline</h2>
        <ol>
          {ACTIONS.map((a) => {
            const allowed = can(a.resource, a.action);
            return (
              <li key={a.id}>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!allowed || busy !== null}
                  title={allowed ? undefined : "Your role lacks this permission"}
                  onClick={() => void ops[a.id]()}
                >
                  {busy === a.id ? "Working…" : a.label}
                </button>
                <small className="muted">{allowed ? a.description : "Not permitted for your role"}</small>
              </li>
            );
          })}
        </ol>
      </section>

      <section className="grid-2">
        <article className="card">
          <h2>Settled transactions per day</h2>
          <p className="muted">Last 30 days · {formatNumber(settledCount)} settled in total</p>
          <BarChart data={chart} title="Settled transactions per day" />
        </article>
        <article className="card">
          <h2>Recent sync events</h2>
          {pg?.recent_logs.length ? (
            <ul className="log-list">
              {pg.recent_logs.map((log) => (
                <li key={log.id}>
                  <strong>
                    {log.source}/{log.event}
                  </strong>
                  <span className="muted">{formatDateTime(log.created_at)}</span>
                  <code>{JSON.stringify(log.detail)}</code>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No events yet ({formatNumber(0)}).</p>
          )}
        </article>
      </section>
    </>
  );
}
