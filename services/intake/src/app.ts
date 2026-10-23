import helmet from "@fastify/helmet";
import rateLimit from "@fastify/rate-limit";
import Fastify, { type FastifyInstance } from "fastify";
import { verify } from "./signature.js";
import type { EventStore, InboundEvent } from "./store.js";

export interface AppDeps {
  store: EventStore;
  signingSecret: string;
  now?: () => number; // unix seconds; injectable so tests control the clock
  rateLimitPerMinute?: number;
  bodyLimitBytes?: number;
}

const MAX_ID_LENGTH = 128;

function parseEvent(raw: string): InboundEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const { id, type, data } = value as Record<string, unknown>;
  if (typeof id !== "string" || id.length < 1 || id.length > MAX_ID_LENGTH) return null;
  if (typeof type !== "string" || !/^[a-z][a-z0-9_.]{0,63}$/.test(type)) return null;
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  return { id, type, data: data as Record<string, unknown> };
}

export async function buildApp(deps: AppDeps): Promise<FastifyInstance> {
  const now = deps.now ?? (() => Math.floor(Date.now() / 1000));
  const app = Fastify({ logger: false, bodyLimit: deps.bodyLimitBytes ?? 64 * 1024 });

  await app.register(helmet);
  await app.register(rateLimit, { max: deps.rateLimitPerMinute ?? 120, timeWindow: "1 minute" });

  // The signature covers the exact bytes received, so keep the raw string and
  // parse it ourselves only after it has been verified.
  app.addContentTypeParser("application/json", { parseAs: "string" }, (_req, body, done) => done(null, body));

  app.get("/health", async () => ({ status: "ok" }));

  app.post("/v1/events", async (request, reply) => {
    const raw = typeof request.body === "string" ? request.body : "";
    const header = request.headers["x-signature"];
    const verdict = verify(deps.signingSecret, Array.isArray(header) ? header[0] : header, raw, now());
    if (!verdict.ok) {
      // One generic answer: do not tell a caller which check failed.
      request.log.warn({ reason: verdict.reason }, "rejected event");
      return reply.code(401).send({ error: "invalid signature" });
    }

    const event = parseEvent(raw);
    if (!event) return reply.code(400).send({ error: "invalid event" });

    const outcome = await deps.store.insert(event);
    return reply.code(outcome === "created" ? 202 : 200).send({ status: outcome === "created" ? "accepted" : "duplicate" });
  });

  return app;
}
