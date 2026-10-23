import { create } from "zustand";

import { api, ApiError } from "../api/client";
import type { IngestionResult, MigrationRun, Overview, PublishResult, SimulateResult } from "../types";

export type SyncAction = "simulate" | "migrate" | "publish" | "ingest";

interface SyncState {
  overview: Overview | null;
  loading: boolean;
  /** The operation currently running, so buttons can show progress and disable each other. */
  busy: SyncAction | null;
  error: string | null;
  notice: string | null;
  /** Bumped after every completed operation; tables refetch when it changes. */
  refreshToken: number;

  refresh: (options?: { silent?: boolean }) => Promise<void>;
  simulate: () => Promise<void>;
  migrate: () => Promise<void>;
  publish: () => Promise<void>;
  ingest: () => Promise<void>;
  clearMessages: () => void;
}

export const useSyncStore = create<SyncState>()((set, get) => {
  async function operate<T>(action: SyncAction, call: () => Promise<T>, describe: (result: T) => string) {
    if (get().busy) return;
    set({ busy: action, error: null, notice: null });
    try {
      const result = await call();
      set({ notice: describe(result) });
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : `${action} failed` });
    } finally {
      set((s) => ({ busy: null, refreshToken: s.refreshToken + 1 }));
      await get().refresh({ silent: true });
    }
  }

  return {
    overview: null,
    loading: false,
    busy: null,
    error: null,
    notice: null,
    refreshToken: 0,

    async refresh({ silent = false } = {}) {
      if (!silent) set({ loading: true });
      try {
        set({ overview: await api<Overview>("/stats/overview"), loading: false });
      } catch (err) {
        set({ loading: false, error: err instanceof ApiError ? err.message : "Could not load statistics" });
      }
    },

    simulate: () =>
      operate(
        "simulate",
        () => api<SimulateResult>("/sync/simulate", { method: "POST", body: { new_rows: 25, changed_rows: 25 } }),
        (r) => `Source updated: ${r.inserted} rows inserted, ${r.updated} changed.`,
      ),

    migrate: () =>
      operate(
        "migrate",
        () => api<MigrationRun>("/sync/migrate", { method: "POST", body: {} }),
        (r) =>
          `Run #${r.run_id} ${r.state}: scanned ${r.rows_scanned} (new ${r.rows_new}, changed ${r.rows_changed}, unchanged ${r.rows_unchanged}).`,
      ),

    publish: () =>
      operate(
        "publish",
        () => api<PublishResult>("/sync/publish", { method: "POST", body: {} }),
        (r) => `Published ${r.published} outbox rows to the queue in ${r.batches} batch(es).`,
      ),

    ingest: () =>
      operate(
        "ingest",
        () => api<IngestionResult>("/sync/ingest", { method: "POST", body: { max_batches: 10 } }),
        (r) => `Processed ${r.claimed} items: ${r.done} done, ${r.retried} retried, ${r.dead} dead.`,
      ),

    clearMessages: () => set({ error: null, notice: null }),
  };
});
