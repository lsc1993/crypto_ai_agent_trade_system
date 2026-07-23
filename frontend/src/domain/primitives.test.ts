import { describe, expect, it } from "vitest";

import { utcIsoStringSchema } from "./primitives";

describe("utcIsoStringSchema", () => {
  it.each([
    "2025-02-29T00:00:00Z",
    "2025-04-31T00:00:00Z",
    "2025-01-01T24:00:00Z",
  ])("rejects impossible UTC calendar timestamp %s", (value) => {
    expect(() => utcIsoStringSchema.parse(value)).toThrow();
  });

  it("accepts a valid leap-day UTC timestamp", () => {
    expect(utcIsoStringSchema.parse("2024-02-29T23:59:59Z")).toBe(
      "2024-02-29T23:59:59Z",
    );
  });
});
