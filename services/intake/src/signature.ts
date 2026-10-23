import { createHmac, timingSafeEqual } from "node:crypto";

/** Header format: `t=<unix seconds>,v1=<hex hmac-sha256 of "<t>.<raw body>">`. */
export const TOLERANCE_SECONDS = 300;

export type Verdict = { ok: true } | { ok: false; reason: "missing" | "malformed" | "stale" | "mismatch" };

export function sign(secret: string, timestamp: number, body: string): string {
  const digest = createHmac("sha256", secret).update(`${timestamp}.${body}`).digest("hex");
  return `t=${timestamp},v1=${digest}`;
}

export function verify(
  secret: string,
  header: string | undefined,
  body: string,
  nowSeconds: number,
  toleranceSeconds = TOLERANCE_SECONDS,
): Verdict {
  if (!header) return { ok: false, reason: "missing" };

  const parts = new Map(header.split(",").map((p) => p.trim().split("=", 2) as [string, string | undefined]));
  const t = Number(parts.get("t"));
  const given = parts.get("v1");
  if (!Number.isInteger(t) || !given || !/^[0-9a-f]{64}$/.test(given)) return { ok: false, reason: "malformed" };

  // Reject replays of an old capture, and timestamps from the future.
  if (Math.abs(nowSeconds - t) > toleranceSeconds) return { ok: false, reason: "stale" };

  const expected = createHmac("sha256", secret).update(`${t}.${body}`).digest();
  const actual = Buffer.from(given, "hex");
  return timingSafeEqual(expected, actual) ? { ok: true } : { ok: false, reason: "mismatch" };
}
