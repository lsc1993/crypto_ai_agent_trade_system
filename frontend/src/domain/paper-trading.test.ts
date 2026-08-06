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

  it("accepts a persisted performance snapshot and rejects a non-canonical PnL", async () => {
    const { paperPerformanceSnapshotSchema } = await import("./paper-trading");
    const snapshot = performanceWire();

    expect(paperPerformanceSnapshotSchema.parse(snapshot)).toMatchObject({
      accountId: snapshot.accountId,
      historyStatus: "complete",
      decisionStats: { fillCount: 2 },
    });
    expect(() =>
      paperPerformanceSnapshotSchema.parse({ ...snapshot, netPnl: 12.5 }),
    ).toThrow();
  });
});

function performanceWire() {
  return {
    accountId: "00000000-0000-4000-8000-000000000801",
    initialCash: "10000",
    currentEquity: "10025",
    netPnl: "25",
    returnFraction: "0.0025",
    realizedPnl: "20",
    unrealizedPnl: "5",
    totalFee: "1",
    maxDrawdownAmount: "10",
    maxDrawdownFraction: "0.001",
    openFillCount: 1,
    closeFillCount: 1,
    profitableCloseCount: 1,
    unprofitableCloseCount: 0,
    breakEvenCloseCount: 0,
    closeWinRate: "1",
    decisionStats: {
      manualIntentCount: 1,
      strategyEvaluationCount: 1,
      noSignalCount: 0,
      riskRejectedCount: 0,
      riskExitCount: 0,
      orderCount: 2,
      fillCount: 2,
    },
    historyStatus: "complete",
    historyStartedAt: "2026-08-04T00:00:00Z",
    historyEndedAt: "2026-08-04T01:00:00Z",
    equityCurve: [
      {
        at: "2026-08-04T00:00:00Z",
        cash: "10000",
        positionQuantity: "0",
        equity: "10000",
        netPnl: "0",
      },
      {
        at: "2026-08-04T01:00:00Z",
        cash: "10025",
        positionQuantity: "0",
        equity: "10025",
        netPnl: "25",
      },
    ],
    generatedAt: "2026-08-04T01:00:00Z",
  };
}

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
