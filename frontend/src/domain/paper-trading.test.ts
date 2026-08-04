import { describe, expect, it } from "vitest";

describe("paper trading domain boundary", () => {
  it("accepts a BTCUSDT paper account and rejects non-canonical decimal input", async () => {
    const { paperAccountDetailSchema } = await import("./paper-trading");
    const account = accountWire();

    expect(paperAccountDetailSchema.parse(account)).toMatchObject({
      id: account.id,
      symbol: "BTCUSDT",
      cash: "10000",
    });
    expect(() =>
      paperAccountDetailSchema.parse({ ...account, cash: 10000 }),
    ).toThrow();
    expect(() =>
      paperAccountDetailSchema.parse({ ...account, symbol: "ETHUSDT" }),
    ).toThrow();
  });
});

export function accountWire() {
  return {
    id: "00000000-0000-4000-8000-000000000907",
    status: "active",
    symbol: "BTCUSDT",
    initialCash: "10000",
    cash: "10000",
    equity: "10000",
    peakEquity: "10000",
    dailyStartEquity: "10000",
    dailyRealizedLoss: "0",
    dailyDay: "2026-08-04",
    cooldownRemaining: 0,
    lastClosedCandleAt: null,
    riskConfig: {
      maxExposureFraction: "0.95",
      stopLossFraction: "0.05",
      dailyLossFraction: "0.03",
      maxDrawdownFraction: "0.1",
      cooldownCandles: 3,
      quantityIncrement: "0.000001",
    },
    executionConfig: {
      feeRate: "0.001",
      slippageRate: "0.0005",
      fillRatio: "1",
    },
    createdAt: "2026-08-04T12:00:00Z",
    archivedAt: null,
    position: {
      quantity: "0",
      averageEntryPrice: null,
      remainingEntryCost: "0",
      openedAt: null,
      updatedAt: "2026-08-04T12:00:00Z",
    },
    latestSnapshot: null,
    orders: [],
    fills: [],
    ledgerEntries: [],
    events: [],
    actionOutcome: null,
  };
}
