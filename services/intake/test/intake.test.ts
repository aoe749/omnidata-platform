import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildApp } from "../src/app.js";
import { sign } from "../src/signature.js";
import { MemoryEventStore } from "../src/store.js";

const SECRET = "test-signing-secret-test-signing-secret";
const NOW = 1_800_000_000;

async function setup(overrides: Partial<Parameters<typeof buildApp>[0]> = {}) {
  const store = new MemoryEventStore();
  const app = await buildApp({ store, signingSecret: SECRET, now: () => NOW, ...overrides });
  return { app, store };
}

function post(app: Awaited<ReturnType<typeof buildApp>>, body: string, signature?: string) {
  return app.inject({
    method: "POST",
    url: "/v1/events",
    headers: { "content-type": "application/json", ...(signature ? { "x-signature": signature } : {}) },
    payload: body,
  });
}

const event = JSON.stringify({ id: "evt_1", type: "transaction.created", data: { amount_cents: 1250 } });

describe("event intake", () => {
  it("accepts a correctly signed event and stores it", async () => {
    const { app, store } = await setup();
    const res = await post(app, event, sign(SECRET, NOW, event));
    assert.equal(res.statusCode, 202);
    assert.equal(store.events.size, 1);
  });

  it("treats redelivery of the same id as a no-op", async () => {
    const { app, store } = await setup();
    await post(app, event, sign(SECRET, NOW, event));
    const second = await post(app, event, sign(SECRET, NOW, event));
    assert.equal(second.statusCode, 200);
    assert.equal(second.json().status, "duplicate");
    assert.equal(store.events.size, 1);
  });

  it("rejects a missing signature", async () => {
    const { app, store } = await setup();
    assert.equal((await post(app, event)).statusCode, 401);
    assert.equal(store.events.size, 0);
  });

  it("rejects a body that was altered after signing", async () => {
    const { app, store } = await setup();
    const tampered = event.replace("1250", "9999");
    assert.equal((await post(app, tampered, sign(SECRET, NOW, event))).statusCode, 401);
    assert.equal(store.events.size, 0);
  });

  it("rejects a signature made with another secret", async () => {
    const { app } = await setup();
    assert.equal((await post(app, event, sign("x".repeat(40), NOW, event))).statusCode, 401);
  });

  it("rejects a replayed old capture and a future timestamp", async () => {
    const { app } = await setup();
    assert.equal((await post(app, event, sign(SECRET, NOW - 301, event))).statusCode, 401);
    assert.equal((await post(app, event, sign(SECRET, NOW + 301, event))).statusCode, 401);
  });

  it("accepts a timestamp inside the tolerance window", async () => {
    const { app } = await setup();
    assert.equal((await post(app, event, sign(SECRET, NOW - 299, event))).statusCode, 202);
  });

  it("rejects a malformed signature header", async () => {
    const { app } = await setup();
    assert.equal((await post(app, event, "garbage")).statusCode, 401);
    assert.equal((await post(app, event, `t=${NOW},v1=nothex`)).statusCode, 401);
  });

  it("does not reveal which check failed", async () => {
    const { app } = await setup();
    const missing = await post(app, event);
    const wrong = await post(app, event, sign("x".repeat(40), NOW, event));
    assert.deepEqual(missing.json(), wrong.json());
  });

  it("rejects a signed but invalid event with 400", async () => {
    const { app, store } = await setup();
    for (const bad of [
      "not json",
      JSON.stringify({ id: "", type: "a.b", data: {} }),
      JSON.stringify({ id: "e1", type: "Bad Type", data: {} }),
      JSON.stringify({ id: "e1", type: "a.b", data: [] }),
      JSON.stringify({ id: "x".repeat(129), type: "a.b", data: {} }),
    ]) {
      assert.equal((await post(app, bad, sign(SECRET, NOW, bad))).statusCode, 400, bad);
    }
    assert.equal(store.events.size, 0);
  });

  it("rejects an oversized body", async () => {
    const { app } = await setup({ bodyLimitBytes: 200 });
    const big = JSON.stringify({ id: "e1", type: "a.b", data: { blob: "x".repeat(500) } });
    assert.equal((await post(app, big, sign(SECRET, NOW, big))).statusCode, 413);
  });

  it("rate limits a noisy client", async () => {
    const { app } = await setup({ rateLimitPerMinute: 3 });
    const codes: number[] = [];
    for (let i = 0; i < 5; i++) codes.push((await app.inject({ method: "GET", url: "/health" })).statusCode);
    assert.deepEqual(codes, [200, 200, 200, 429, 429]);
  });

  it("sets security headers", async () => {
    const { app } = await setup();
    const res = await app.inject({ method: "GET", url: "/health" });
    assert.equal(res.headers["x-content-type-options"], "nosniff");
    assert.ok(res.headers["content-security-policy"]);
  });
});
