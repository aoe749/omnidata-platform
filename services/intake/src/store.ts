export interface InboundEvent {
  id: string;
  type: string;
  data: Record<string, unknown>;
}

export type InsertOutcome = "created" | "duplicate";

export interface EventStore {
  /** Idempotent: inserting an id that already exists changes nothing. */
  insert(event: InboundEvent): Promise<InsertOutcome>;
}

export class MemoryEventStore implements EventStore {
  readonly events = new Map<string, InboundEvent>();

  async insert(event: InboundEvent): Promise<InsertOutcome> {
    if (this.events.has(event.id)) return "duplicate";
    this.events.set(event.id, event);
    return "created";
  }
}
