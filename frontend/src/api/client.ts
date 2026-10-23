/** Minimal typed fetch wrapper. Auth is injected via `configureClient` to avoid import cycles with the stores. */

const BASE: string = import.meta.env.VITE_API_BASE ?? "/api/v1";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ClientHandlers {
  getToken: () => string | null;
  onUnauthorized: () => void;
}

let handlers: ClientHandlers = { getToken: () => null, onUnauthorized: () => undefined };

export function configureClient(next: ClientHandlers): void {
  handlers = next;
}

type QueryValue = string | number | undefined;

interface RequestOptions {
  method?: "GET" | "POST" | "DELETE";
  body?: unknown;
  query?: Record<string, QueryValue>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg?: string }) => d.msg).join("; ");
  } catch {
    /* non-JSON error body */
  }
  return `Request failed (${response.status})`;
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const token = handlers.getToken();
  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? "GET",
    signal: options.signal,
    headers: {
      ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  if (response.status === 401 && token) handlers.onUnauthorized();
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response));
  return response;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options);
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/** Authenticated file download (the bearer header rules out a plain <a href>). */
export async function downloadFile(path: string, query: Record<string, QueryValue>, filename: string): Promise<void> {
  const blob = await (await send(path, { query })).blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
