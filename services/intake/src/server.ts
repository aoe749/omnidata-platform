import pg from "pg";
import { buildApp } from "./app.js";
import { PgEventStore } from "./pgStore.js";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

const signingSecret = required("INTAKE_SIGNING_SECRET");
if (signingSecret.length < 32) throw new Error("INTAKE_SIGNING_SECRET must be at least 32 characters");

const pool = new pg.Pool({
  host: process.env.POSTGRES_HOST ?? "localhost",
  port: Number(process.env.POSTGRES_PORT ?? 5432),
  user: process.env.POSTGRES_USER ?? "omnidata",
  password: required("POSTGRES_PASSWORD"),
  database: process.env.POSTGRES_DATABASE ?? "omnidata",
  max: 5,
});

const app = await buildApp({ store: new PgEventStore(pool), signingSecret });

const shutdown = async () => {
  await app.close();
  await pool.end();
};
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

await app.listen({ host: "0.0.0.0", port: Number(process.env.PORT ?? 3000) });
