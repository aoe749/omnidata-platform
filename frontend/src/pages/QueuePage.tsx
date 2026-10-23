import type { ColumnDef } from "@tanstack/react-table";
import { useCallback, useMemo } from "react";

import { api } from "../api/client";
import { DataTable, type FilterField } from "../components/DataTable";
import { StatusBadge } from "../components/widgets";
import { formatDateTime } from "../lib/format";
import { toParams } from "../lib/query";
import { useSyncStore } from "../store/sync";
import type { Page, QueueItem, TableQuery } from "../types";

const FILTERS: FilterField[] = [
  { key: "search", label: "Source id", type: "text", placeholder: "e.g. 1042" },
  {
    key: "status",
    label: "Status",
    type: "select",
    options: ["queued", "processing", "done", "dead"].map((s) => ({ value: s, label: s })),
  },
];

export function QueuePage() {
  const refreshToken = useSyncStore((s) => s.refreshToken);

  const columns = useMemo<ColumnDef<QueueItem, any>[]>( // eslint-disable-line @typescript-eslint/no-explicit-any
    () => [
      { accessorKey: "id", header: "Queue id" },
      { accessorKey: "source_id", header: "Source id" },
      { accessorKey: "status", header: "Status", cell: ({ getValue }) => <StatusBadge value={String(getValue())} /> },
      { accessorKey: "attempts", header: "Attempts" },
      { accessorKey: "available_at", header: "Available", cell: ({ getValue }) => formatDateTime(String(getValue())) },
      { accessorKey: "created_at", header: "Created", cell: ({ getValue }) => formatDateTime(String(getValue())) },
      {
        accessorKey: "last_error",
        header: "Last error",
        enableSorting: false,
        cell: ({ getValue }) => <span className="truncate">{(getValue() as string | null) ?? "—"}</span>,
      },
    ],
    [],
  );

  const fetchPage = useCallback(
    (query: TableQuery, signal: AbortSignal) => api<Page<QueueItem>>("/sync/queue", { query: toParams(query), signal }),
    [],
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Work queue</h1>
          <p className="muted">PostgreSQL queue claimed with FOR UPDATE SKIP LOCKED. Failures retry with back-off, then dead-letter.</p>
        </div>
      </div>
      <DataTable<QueueItem>
        caption="Work queue items"
        columns={columns}
        fetchPage={fetchPage}
        filters={FILTERS}
        defaultSort={[{ id: "id", desc: true }]}
        refreshToken={refreshToken}
      />
    </>
  );
}
