import { describe, expect, it, vi } from "vitest";

import { backtestRequestSchema } from "../../domain/backtest";
import type { MarketDetail, MarketSummary } from "../../domain/market";
import { tradeDraftSchema } from "../../domain/trade";
import { HttpWorkbenchApi } from "./http-workbench-api";
import { WorkbenchResponseError } from "./http-transport";

const liveSummary: MarketSummary = {
  symbol: "BTCUSDT",
  price: "68000.30",
  change24h: "1.25",
  volume24h: "123456.789",
  fundingRate: "0.00010000",
  openInterest: "1234.5678",
  freshness: {
    status: "fresh",
    source: "binance_usdm_public_rest",
    observedAt: "2026-07-28T12:00:00Z",
    fetchedAt: "2026-07-28T12:00:00Z",
  },
};

const liveDetail: MarketDetail = {
  summary: liveSummary,
  series: [
    {
      timeframe: "15m",
      candles: [
        {
          symbol: "BTCUSDT",
          timeframe: "15m",
          openTime: "2026-07-28T11:45:00Z",
          closeTime: "2026-07-28T11:59:59Z",
          open: "68000.10",
          high: "68001.20",
          low: "67999.90",
          close: "68000.30",
          volume: "12.34",
        },
      ],
    },
  ],
  news: [],
};

const dashboardWire = {
  markets: [
    liveSummary,
    {
      symbol: "ETHUSDT",
      price: "3500.10",
      change24h: "-0.75",
      volume24h: "98765.4321",
      fundingRate: "-0.00005000",
      openInterest: "876.5432",
      freshness: {
        status: "fresh",
        source: "binance_usdm_public_rest",
        observedAt: "2026-07-28T12:00:00Z",
        fetchedAt: "2026-07-28T12:00:00Z",
      },
    },
  ],
  news: [],
  recentReports: [
    {
      id: "00000000-0000-4000-8000-000000000401",
      analysisId: "00000000-0000-4000-8000-000000000402",
      symbol: "BTCUSDT",
      status: "completed",
      title: "BTC market analysis",
      summary: "Market conditions are stable.",
      createdAt: "2026-07-28T12:00:00Z",
      dataCutoffAt: "2026-07-28T11:55:00Z",
      generatorKind: "deterministic",
    },
  ],
  generatedAt: "2026-07-28T12:00:00Z",
} as const;

describe("HttpWorkbenchApi market reads", () => {
  it("loads the schema-validated dashboard snapshot from the API", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(Response.json(dashboardWire)),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(api.getDashboard()).resolves.toEqual(dashboardWire);

    const requestUrl = new URL(
      (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as URL,
    );
    expect(requestUrl.pathname).toBe("/api/v1/dashboard");
  });

  it("rejects a dashboard response that does not match the contract", async () => {
    const malformedDashboardWire: Omit<typeof dashboardWire, "generatedAt"> = {
      markets: dashboardWire.markets,
      news: dashboardWire.news,
      recentReports: dashboardWire.recentReports,
    };
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(Response.json(malformedDashboardWire)),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(api.getDashboard()).rejects.toBeInstanceOf(
      WorkbenchResponseError,
    );
  });

  it("maps the bounded summary endpoint to the existing market contract", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(Response.json({ items: [liveSummary] })),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(api.listMarketSummaries()).resolves.toEqual([liveSummary]);

    const requestUrl = new URL(
      (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as URL,
    );
    expect(requestUrl.pathname).toBe("/api/v1/markets");
    expect(requestUrl.searchParams.getAll("symbols")).toEqual([
      "BTCUSDT",
      "ETHUSDT",
    ]);
  });

  it("maps requested timeframes to the bounded market detail endpoint", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(Response.json(liveDetail)),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(
      api.getMarket({ symbol: "BTCUSDT", timeframes: ["15m"] }),
    ).resolves.toEqual(liveDetail);

    const requestUrl = new URL(
      (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as URL,
    );
    expect(requestUrl.pathname).toBe("/api/v1/market/BTCUSDT");
    expect(requestUrl.searchParams.getAll("timeframes")).toEqual(["15m"]);
  });

  it("uses the persisted research API only when explicitly configured", async () => {
    const fetchImpl: typeof fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ items: [liveDetail.summary] }))
      .mockResolvedValueOnce(Response.json(liveDetail));
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      marketDataSource: "research",
      fetchImpl,
    });

    await expect(api.listMarketSummaries()).resolves.toEqual([liveDetail.summary]);
    await expect(
      api.getMarket({ symbol: "BTCUSDT", timeframes: ["15m"] }),
    ).resolves.toEqual(liveDetail);

    const summaryUrl = new URL(
      (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as URL,
    );
    const detailUrl = new URL(
      (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[1]?.[0] as URL,
    );
    expect(summaryUrl.pathname).toBe("/api/v1/research/markets");
    expect(detailUrl.pathname).toBe("/api/v1/research/market/BTCUSDT");
  });
});

describe("HttpWorkbenchApi trade journal reads and writes", () => {
  it("maps real trade and analytics endpoints without leaking frontend-only fields", async () => {
    const fetchImpl: typeof fetch = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({ items: [tradeWire], page: 1, page_size: 20, total: 1 }),
      )
      .mockResolvedValueOnce(Response.json(tradeWire))
      .mockResolvedValueOnce(Response.json(tradeWire))
      .mockResolvedValueOnce(Response.json(analyticsWire));
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });
    const draft = tradeDraftSchema.parse({
      symbol: "BTCUSDT",
      direction: "long",
      horizon: "short_term",
      labels: ["manual"],
      linkedReportId: null,
      leverage: "2",
      legs: [
        {
          id: "00000000-0000-4000-8000-000000000101",
          action: "open",
          executedAt: "2026-07-31T12:00:00Z",
          price: "100",
          quantity: "1",
          fee: "0.1",
        },
        {
          id: "00000000-0000-4000-8000-000000000102",
          action: "close",
          executedAt: "2026-07-31T13:00:00Z",
          price: "120",
          quantity: "1",
          fee: "0.2",
        },
      ],
      fundingCashflows: [
        {
          id: "00000000-0000-4000-8000-000000000103",
          occurredAt: "2026-07-31T12:30:00Z",
          amount: "-0.25",
          reason: "funding payment",
        },
      ],
      thesis: "manual thesis",
      review: "manual review",
    });

    await expect(api.listTrades({ page: 1, pageSize: 20 })).resolves.toMatchObject({
      items: [
        {
          id: tradeWire.id,
          fundingCashflows: tradeWire.cashflows,
        },
      ],
    });
    await expect(api.createTrade(draft)).resolves.toMatchObject({
      fundingCashflows: tradeWire.cashflows,
    });
    await expect(api.updateTrade("trade/id", draft)).resolves.toMatchObject({
      id: tradeWire.id,
    });
    await expect(
      api.getAnalytics({ symbol: "BTCUSDT", from: "2026-07-31T00:00:00Z" }),
    ).resolves.toMatchObject({ profitFactor: null });

    const calls = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls;
    expect(new URL(calls[0]?.[0] as URL).pathname).toBe("/api/v1/trades");
    const createRequest = calls[1]?.[1] as RequestInit;
    if (typeof createRequest.body !== "string") {
      throw new Error("Expected the create request body to be JSON text");
    }
    const createBody = JSON.parse(createRequest.body) as {
      cashflows: unknown;
      fundingCashflows?: unknown;
    };
    expect(createBody.cashflows).toEqual(draft.fundingCashflows);
    expect(createBody.fundingCashflows).toBeUndefined();
    expect(new URL(calls[2]?.[0] as URL).pathname).toBe("/api/v1/trades/trade%2Fid");
    const analyticsUrl = new URL(calls[3]?.[0] as URL);
    expect(analyticsUrl.pathname).toBe("/api/v1/analytics");
    expect(analyticsUrl.searchParams.get("symbol")).toBe("BTCUSDT");
    expect(analyticsUrl.searchParams.get("from")).toBe("2026-07-31T00:00:00Z");
  });
});

describe("HttpWorkbenchApi deterministic backtests", () => {
  it("posts a validated request and maps persisted list and detail results", async () => {
    const fetchImpl: typeof fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json(backtestWire))
      .mockResolvedValueOnce(
        Response.json({ items: [backtestWire], page: 2, page_size: 5, total: 1 }),
      )
      .mockResolvedValueOnce(Response.json(backtestWire));
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });
    const request = backtestRequestSchema.parse({
      symbol: "BTCUSDT",
      timeframe: "1h",
      startAt: "2026-07-01T00:00:00Z",
      endAt: "2026-07-02T00:00:00Z",
      initialCash: "10000",
    });

    await expect(api.startBacktest(request)).resolves.toMatchObject({
      status: "completed",
      summary: { finalEquity: "10123.45" },
    });
    await expect(api.listBacktests({ page: 2, pageSize: 5 })).resolves.toMatchObject({
      page: 2,
      pageSize: 5,
      total: 1,
    });
    await expect(api.getBacktest(backtestWire.id)).resolves.toMatchObject({
      id: backtestWire.id,
      events: [{ kind: "completed" }],
    });

    const calls = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls;
    expect(new URL(calls[0]?.[0] as URL).pathname).toBe("/api/v1/backtests");
    const createRequest = calls[0]?.[1] as RequestInit;
    expect(createRequest.method).toBe("POST");
    if (typeof createRequest.body !== "string") {
      throw new Error("Expected the backtest request body to be JSON text");
    }
    expect(JSON.parse(createRequest.body)).toEqual(request);
    const listUrl = new URL(calls[1]?.[0] as URL);
    expect(listUrl.pathname).toBe("/api/v1/backtests");
    expect(listUrl.searchParams.get("page")).toBe("2");
    expect(listUrl.searchParams.get("page_size")).toBe("5");
    expect(new URL(calls[2]?.[0] as URL).pathname).toBe(
      `/api/v1/backtests/${backtestWire.id}`,
    );
  });
});

describe("HttpWorkbenchApi paper trading performance", () => {
  it("reads and validates the persisted local performance endpoint", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(Response.json(paperPerformanceWire)),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(
      api.getPaperPerformance(paperPerformanceWire.accountId),
    ).resolves.toMatchObject({
      currentEquity: "10025",
      historyStatus: "complete",
      decisionStats: { fillCount: 2 },
    });

    const requestUrl = new URL(
      (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as URL,
    );
    expect(requestUrl.pathname).toBe(
      `/api/v1/paper-accounts/${paperPerformanceWire.accountId}/performance`,
    );
  });
});

const tradeWire = {
  id: "00000000-0000-4000-8000-000000000333",
  symbol: "BTCUSDT",
  direction: "long",
  horizon: "short_term",
  labels: ["manual"],
  linkedReportId: null,
  leverage: "2",
  legs: [
    {
      id: "00000000-0000-4000-8000-000000000101",
      action: "open",
      executedAt: "2026-07-31T12:00:00Z",
      price: "100",
      quantity: "1",
      fee: "0.1",
    },
    {
      id: "00000000-0000-4000-8000-000000000102",
      action: "close",
      executedAt: "2026-07-31T13:00:00Z",
      price: "120",
      quantity: "1",
      fee: "0.2",
    },
  ],
  cashflows: [
    {
      id: "00000000-0000-4000-8000-000000000103",
      occurredAt: "2026-07-31T12:30:00Z",
      amount: "-0.25",
      reason: "funding payment",
    },
  ],
  thesis: "manual thesis",
  review: "manual review",
  status: "closed",
  netPnl: "19.45",
  openedAt: "2026-07-31T12:00:00Z",
  closedAt: "2026-07-31T13:00:00Z",
  createdAt: "2026-07-31T14:00:00Z",
  updatedAt: "2026-07-31T14:00:00Z",
} as const;

const backtestWire = {
  id: "00000000-0000-4000-8000-000000000801",
  status: "completed",
  symbol: "BTCUSDT",
  timeframe: "1h",
  startAt: "2026-07-01T00:00:00Z",
  endAt: "2026-07-02T00:00:00Z",
  initialCash: "10000",
  strategyId: "sma_crossover",
  strategyVersion: "v1",
  riskConfig: {
    maxExposureFraction: "0.95",
    stopLossFraction: "0.05",
    dailyLossFraction: "0.03",
    maxDrawdownFraction: "0.15",
    cooldownCandles: 3,
    quantityIncrement: "0.000001",
  },
  executionConfig: {
    feeRate: "0.001",
    slippageRate: "0.0005",
    fillRatio: "1",
  },
  createdAt: "2026-07-02T00:00:00Z",
  finishedAt: "2026-07-02T00:01:00Z",
  summary: {
    initialCash: "10000",
    finalEquity: "10123.45",
    netPnl: "123.45",
    realizedPnl: "100",
    unrealizedPnl: "23.45",
    returnFraction: "0.012345",
    maxDrawdownFraction: "0.03",
    winRate: "0.5",
    profitFactor: "1.2",
    closedTradeCount: 2,
    fillCount: 4,
    rejectionCount: 0,
    openPositionQuantity: "0",
    candleCount: 24,
    snapshotHash: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  },
  failureCode: null,
  failureMessage: null,
  closedTrades: [],
  events: [
    {
      sequence: 0,
      kind: "completed",
      occurredAt: "2026-07-02T00:00:00Z",
      candleSequence: 51,
      idempotencyKey: null,
      payload: { final_equity: "10123.45" },
    },
  ],
} as const;

const analyticsWire = {
  netPnl: "19.45",
  winRate: "1",
  profitFactor: null,
  expectancy: "19.45",
  maxDrawdown: "0",
  equityCurve: [
    {
      at: "2026-07-31T13:00:00Z",
      equity: "19.45",
      netPnl: "19.45",
    },
  ],
  tradeCalendar: [
    {
      at: "2026-07-31T00:00:00Z",
      netPnl: "19.45",
      tradeCount: 1,
    },
  ],
  generatedAt: "2026-07-31T14:00:00Z",
} as const;

const paperPerformanceWire = {
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
} as const;
