import type { Pool } from "pg";
import type { EventStore, InboundEvent, InsertOutcome } from "./store.js";

export class PgEventStore implements EventStore {
  constructor(private readonly pool: Pool) {}

  async insert(event: InboundEvent): Promise<InsertOutcome> {
    // The primary key makes redelivery a no-op; rowCount tells the two cases apart.
    const result = await this.pool.query(
      "INSERT INTO inbound_events (event_id, event_type, payload) VALUES ($1, $2, $3) ON CONFLICT (event_id) DO NOTHING",
      [event.id, event.type, JSON.stringify(event.data)],
    );
    return result.rowCount === 1 ? "created" : "duplicate";
  }
}
