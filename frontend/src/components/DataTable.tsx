import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type OnChangeFn,
  type PaginationState,
  type SortingState,
} from "@tanstack/react-table";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { cleanFilters } from "../lib/query";
import { useDebouncedValue } from "../lib/useDebouncedValue";
import type { Page, TableQuery } from "../types";

export interface FilterField {
  key: string;
  label: string;
  type: "text" | "number" | "date" | "select";
  placeholder?: string;
  options?: { value: string; label: string }[];
}

interface DataTableProps<T> {
  /** Accessible table name (rendered as a visually-hidden caption). */
  caption: string;
  columns: ColumnDef<T, any>[]; // eslint-disable-line @typescript-eslint/no-explicit-any
  /**
   * Loads one page. Receives the full query (page, sort, filters) and an
   * AbortSignal that fires when a newer request supersedes this one.
   * Sorting/pagination/filtering all happen on the server.
   */
  fetchPage: (query: TableQuery, signal: AbortSignal) => Promise<Page<T>>;
  filters?: FilterField[];
  defaultSort?: SortingState;
  pageSizeOptions?: number[];
  /** Change this value to force a refetch (e.g. after a sync operation). */
  refreshToken?: number;
  /** Extra controls rendered on the right of the toolbar. */
  toolbar?: ReactNode;
  /** Called with the query about to be fetched, e.g. so an export button can reuse the filters. */
  onQueryChange?: (query: TableQuery) => void;
  emptyMessage?: string;
}

const EMPTY: never[] = [];
const FILTER_DEBOUNCE_MS = 350;

export function DataTable<T>({
  caption,
  columns,
  fetchPage,
  filters = [],
  defaultSort = [],
  pageSizeOptions = [10, 25, 50, 100],
  refreshToken = 0,
  toolbar,
  onQueryChange,
  emptyMessage = "No records match the current filters.",
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>(defaultSort);
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: pageSizeOptions[1] ?? 25 });
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [data, setData] = useState<Page<T> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Text inputs update `draft` on every keystroke; the query only follows after a pause.
  const debounced = useDebouncedValue(draft, FILTER_DEBOUNCE_MS);

  // Always call the latest callbacks without making them effect dependencies.
  const fetchRef = useRef(fetchPage);
  const queryChangeRef = useRef(onQueryChange);
  useEffect(() => {
    fetchRef.current = fetchPage;
    queryChangeRef.current = onQueryChange;
  });

  useEffect(() => {
    const controller = new AbortController();
    const sort = sorting[0];
    const query: TableQuery = {
      page: pagination.pageIndex + 1,
      page_size: pagination.pageSize,
      sort_by: sort?.id,
      sort_dir: sort?.desc ? "desc" : "asc",
      filters: cleanFilters(debounced),
    };
    queryChangeRef.current?.(query);
    setLoading(true);
    setError(null);
    fetchRef
      .current(query, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        // The data shrank under us (e.g. rows were archived): jump back to the last real page.
        const lastPage = Math.max(0, Math.ceil(result.total / pagination.pageSize) - 1);
        if (result.items.length === 0 && pagination.pageIndex > lastPage) {
          setPagination((p) => ({ ...p, pageIndex: lastPage }));
          return;
        }
        setData(result);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return; // superseded request, not an error
        setError(err instanceof Error ? err.message : "Failed to load data");
        setLoading(false);
      });
    return () => controller.abort();
  }, [pagination.pageIndex, pagination.pageSize, sorting, debounced, refreshToken]);

  const backToFirstPage = () => setPagination((p) => (p.pageIndex === 0 ? p : { ...p, pageIndex: 0 }));

  const onSortingChange: OnChangeFn<SortingState> = (updater) => {
    setSorting((prev) => (typeof updater === "function" ? updater(prev) : updater));
    backToFirstPage();
  };

  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / pagination.pageSize));

  const table = useReactTable({
    data: data?.items ?? EMPTY,
    columns,
    state: { sorting, pagination },
    pageCount,
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    enableSortingRemoval: false,
    onSortingChange,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
  });

  const setFilter = (key: string, value: string) => {
    setDraft((d) => ({ ...d, [key]: value }));
    backToFirstPage();
  };

  const hasFilters = useMemo(() => Object.values(draft).some((v) => v.trim() !== ""), [draft]);
  const first = total === 0 ? 0 : pagination.pageIndex * pagination.pageSize + 1;
  const last = Math.min(total, (pagination.pageIndex + 1) * pagination.pageSize);

  return (
    <section className="table-card" aria-busy={loading}>
      {(filters.length > 0 || toolbar) && (
        <div className="table-toolbar">
          <div className="filters">
            {filters.map((field) => (
              <label key={field.key} className="filter">
                <span>{field.label}</span>
                {field.type === "select" ? (
                  <select value={draft[field.key] ?? ""} onChange={(e) => setFilter(field.key, e.target.value)}>
                    <option value="">All</option>
                    {field.options?.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={field.type === "text" ? "search" : field.type}
                    min={field.type === "number" ? 0 : undefined}
                    placeholder={field.placeholder}
                    value={draft[field.key] ?? ""}
                    onChange={(e) => setFilter(field.key, e.target.value)}
                  />
                )}
              </label>
            ))}
            {hasFilters && (
              <button type="button" className="btn btn-ghost" onClick={() => { setDraft({}); backToFirstPage(); }}>
                Clear filters
              </button>
            )}
          </div>
          {toolbar && <div className="toolbar-actions">{toolbar}</div>}
        </div>
      )}

      {error && (
        <div role="alert" className="banner banner-error">
          {error}
        </div>
      )}

      <div className="table-scroll">
        <table className={loading ? "is-loading" : undefined}>
          <caption className="sr-only">{caption}</caption>
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
                    >
                      {header.isPlaceholder ? null : header.column.getCanSort() ? (
                        <button type="button" className="sort-btn" onClick={header.column.getToggleSortingHandler()}>
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <span aria-hidden="true" className="sort-icon">
                            {sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : "↕"}
                          </span>
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            ))}
            {!loading && !error && data?.items.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="empty">
                  {emptyMessage}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="table-footer">
        <span aria-live="polite">
          {total === 0 ? "0 results" : `${first.toLocaleString()}–${last.toLocaleString()} of ${total.toLocaleString()}`}
        </span>
        <div className="pager">
          <label>
            Rows
            <select
              value={pagination.pageSize}
              onChange={(e) => setPagination({ pageIndex: 0, pageSize: Number(e.target.value) })}
            >
              {pageSizeOptions.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn" onClick={() => table.setPageIndex(0)} disabled={pagination.pageIndex === 0}>
            «
          </button>
          <button type="button" className="btn" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>
            Previous
          </button>
          <span>
            Page {pagination.pageIndex + 1} / {pageCount}
          </span>
          <button type="button" className="btn" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
            Next
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => table.setPageIndex(pageCount - 1)}
            disabled={pagination.pageIndex >= pageCount - 1}
          >
            »
          </button>
        </div>
      </div>
    </section>
  );
}
