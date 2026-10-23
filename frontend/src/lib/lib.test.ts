import { describe, expect, it } from "vitest";

import { hasAction } from "./permissions";
import { cleanFilters, toParams } from "./query";

const BITS = { read: 1, create: 2, update: 4, delete: 8, export: 16 };

describe("hasAction (bitmask)", () => {
  const profile = { permissions: { transactions: 1 | 16, sync: 1 }, action_bits: BITS };

  it("grants only the bits that are set", () => {
    expect(hasAction(profile, "transactions", "read")).toBe(true);
    expect(hasAction(profile, "transactions", "export")).toBe(true);
    expect(hasAction(profile, "transactions", "delete")).toBe(false);
    expect(hasAction(profile, "sync", "create")).toBe(false);
  });

  it("denies unknown resources and anonymous users", () => {
    expect(hasAction(profile, "users", "read")).toBe(false);
    expect(hasAction(null, "sync", "read")).toBe(false);
  });
});

describe("table query serialisation", () => {
  it("drops blank filters and trims values", () => {
    expect(cleanFilters({ a: " x ", b: "  ", c: "" })).toEqual({ a: " x " });
    expect(
      toParams({ page: 2, page_size: 25, sort_by: "amount_cents", sort_dir: "desc", filters: { search: " acc " } }),
    ).toEqual({ page: 2, page_size: 25, sort_dir: "desc", sort_by: "amount_cents", search: "acc" });
  });

  it("omits sort_by when unsorted", () => {
    expect(toParams({ page: 1, page_size: 10, sort_dir: "asc", filters: {} })).toEqual({
      page: 1,
      page_size: 10,
      sort_dir: "asc",
    });
  });
});
