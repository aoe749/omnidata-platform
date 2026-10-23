import type { ColumnDef } from "@tanstack/react-table";
import { useCallback, useMemo } from "react";

import { api } from "../api/client";
import { DataTable, type FilterField } from "../components/DataTable";
import { StatusBadge } from "../components/widgets";
import { formatDateTime, formatNumber } from "../lib/format";
import { toParams } from "../lib/query";
import { useSyncStore } from "../store/sync";
import type { MigrationRun, Page, TableQuery } from "../types";

const FILTERS: FilterField[] = [
  {
    key: "state",
    label: "State",
    type: "select",
    options: ["running", "completed", "failed"].map((s) => ({ value: s, label: s })),
  },
];

const num = ({ getValue }: { getValue: () => unknown }) => <span className="num">{formatNumber(Number(getValue()))}</span>;

export function RunsPage() {
  const refreshToken = useSyncStore((s) => s.refreshToken);

  const columns = useMemo<ColumnDef<MigrationRun, any>[]>( // eslint-disable-line @typescript-eslint/no-explicit-any
    () => [
      { accessorKey: "run_id", header: "Run" },
      { accessorKey: "state", header: "State", cell: ({ getValue }) => <StatusBadge value={String(getValue())} /> },
      { accessorKey: "rows_scanned", header: "Scanned", cell: num },
      { accessorKey: "rows_new", header: "New", enableSorting: false, cell: num },
      { accessorKey: "rows_changed", header: "Changed", enableSorting: false, cell: num },
      { accessorKey: "rows_unchanged", header: "Unchanged", enableSorting: false, cell: num },
      { accessorKey: "cursor_last_id", header: "Cursor", enableSorting: false, cell: num },
      { accessorKey: "started_at", header: "Started", cell: ({ getValue }) => formatDateTime(String(getValue())) },
      {
        accessorKey: "last_error",
        header: "Error",
        enableSorting: false,
        cell: ({ getValue }) => <span className="truncate">{(getValue() as string | null) ?? "—"}</span>,
      },
    ],
    [],
  );

  const fetchPage = useCallback(
    (query: TableQuery, signal: AbortSignal) =>
      api<Page<MigrationRun>>("/sync/runs", { query: toParams(query), signal }),
    [],
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Migration runs</h1>
          <p className="muted">Each run checkpoints its cursor per batch, so a failed run resumes where it stopped.</p>
        </div>
      </div>
      <DataTable<MigrationRun>
        caption="Migration runs"
        columns={columns}
        fetchPage={fetchPage}
        filters={FILTERS}
        defaultSort={[{ id: "run_id", desc: true }]}
        pageSizeOptions={[10, 25, 50]}
        refreshToken={refreshToken}
      />
    </>
  );
}
