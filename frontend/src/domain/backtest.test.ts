import { describe, expect, it } from "vitest";

import { backtestRequestSchema } from "./backtest";

const request = {
  symbol: "BTCUSDT",
  timeframe: "1h",
  startAt: "2026-07-01T00:00:00Z",
  endAt: "2026-07-02T00:00:00Z",
  initialCash: "10000",
} as const;

describe("backtestRequestSchema", () => {
  it("keeps a valid BTCUSDT 1h request as decimal and UTC strings", () => {
    expect(backtestRequestSchema.parse(request)).toEqual(request);
  });

  it.each([
    { ...request, symbol: "ETHUSDT" },
    { ...request, timeframe: "4h" },
    { ...request, initialCash: "0" },
    { ...request, startAt: request.endAt },
  ])("rejects a request outside the deterministic backtest boundary", (input) => {
    expect(() => backtestRequestSchema.parse(input)).toThrow();
  });
});
