import type { ColumnDef } from "@tanstack/react-table";
import { useCallback, useMemo, useRef, useState } from "react";

import { api, downloadFile } from "../api/client";
import { DataTable, type FilterField } from "../components/DataTable";
import { StatusBadge } from "../components/widgets";
import { formatDateTime, formatMoney } from "../lib/format";
import { toParams } from "../lib/query";
import { useAuthStore } from "../store/auth";
import { useSyncStore } from "../store/sync";
import type { Page, TableQuery, Transaction } from "../types";

const FILTERS: FilterField[] = [
  { key: "search", label: "Search", type: "text", placeholder: "Account or number" },
  {
    key: "currency",
    label: "Currency",
    type: "select",
    options: ["USD", "EUR", "GBP"].map((c) => ({ value: c, label: c })),
  },
  {
    key: "status",
    label: "Status",
    type: "select",
    options: ["settled", "pending", "reversed"].map((s) => ({ value: s, label: s })),
  },
  { key: "min_amount_cents", label: "Min (cents)", type: "number" },
  { key: "max_amount_cents", label: "Max (cents)", type: "number" },
  { key: "occurred_from", label: "From", type: "date" },
  { key: "occurred_to", label: "To", type: "date" },
];

export function TransactionsPage() {
  const refreshToken = useSyncStore((s) => s.refreshToken);
  const canExport = useAuthStore((s) => s.can("transactions", "export"));
  const lastQuery = useRef<TableQuery | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const columns = useMemo<ColumnDef<Transaction, any>[]>( // eslint-disable-line @typescript-eslint/no-explicit-any
    () => [
      { accessorKey: "ingest_no", header: "Number" },
      { accessorKey: "account_ref", header: "Account" },
      {
        accessorKey: "amount_cents",
        header: "Amount",
        cell: ({ row }) => <span className="num">{formatMoney(row.original.amount_cents, row.original.currency)}</span>,
      },
      { accessorKey: "currency", header: "Currency" },
      { accessorKey: "status", header: "Status", cell: ({ getValue }) => <StatusBadge value={String(getValue())} /> },
      { accessorKey: "occurred_at", header: "Occurred", cell: ({ getValue }) => formatDateTime(String(getValue())) },
      { accessorKey: "ingested_at", header: "Ingested", cell: ({ getValue }) => formatDateTime(String(getValue())) },
    ],
    [],
  );

  const fetchPage = useCallback(
    (query: TableQuery, signal: AbortSignal) =>
      api<Page<Transaction>>("/transactions", { query: toParams(query), signal }),
    [],
  );

  const exportCsv = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const { filters = {} } = lastQuery.current ?? {};
      await downloadFile("/transactions/export", filters, "transactions.csv");
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Transactions</h1>
          <p className="muted">Ingested into PostgreSQL. Sorting, filtering and paging run on the server.</p>
        </div>
      </div>
      {exportError && (
        <div role="alert" className="banner banner-error">
          {exportError}
        </div>
      )}
      <DataTable<Transaction>
        caption="Ingested transactions"
        columns={columns}
        fetchPage={fetchPage}
        filters={FILTERS}
        defaultSort={[{ id: "occurred_at", desc: true }]}
        refreshToken={refreshToken}
        onQueryChange={(q) => (lastQuery.current = q)}
        toolbar={
          canExport && (
            <button type="button" className="btn" onClick={() => void exportCsv()} disabled={exporting}>
              {exporting ? "Exporting…" : "Export CSV"}
            </button>
          )
        }
      />
    </>
  );
}
