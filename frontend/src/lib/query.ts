import type { TableQuery } from "../types";

/** Flatten a table query into URL parameters (drops empty filters). */
export function toParams(query: TableQuery): Record<string, string | number> {
  const params: Record<string, string | number> = {
    page: query.page,
    page_size: query.page_size,
    sort_dir: query.sort_dir,
  };
  if (query.sort_by) params.sort_by = query.sort_by;
  for (const [key, value] of Object.entries(query.filters)) {
    if (value.trim() !== "") params[key] = value.trim();
  }
  return params;
}

/** Keep only non-blank filter values. */
export function cleanFilters(raw: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(raw).filter(([, v]) => v.trim() !== ""));
}
