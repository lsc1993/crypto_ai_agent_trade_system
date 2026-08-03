import { describe, expect, it, vi } from "vitest";

import type { MarketDetail, MarketSummary } from "../../domain/market";
import { tradeDraftSchema } from "../../domain/trade";
import { HttpWorkbenchApi } from "./http-workbench-api";

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

describe("HttpWorkbenchApi market reads", () => {
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
          id: "00000000-0000-0000-0000-000000000101",
          action: "open",
          executedAt: "2026-07-31T12:00:00Z",
          price: "100",
          quantity: "1",
          fee: "0.1",
        },
        {
          id: "00000000-0000-0000-0000-000000000102",
          action: "close",
          executedAt: "2026-07-31T13:00:00Z",
          price: "120",
          quantity: "1",
          fee: "0.2",
        },
      ],
      fundingCashflows: [
        {
          id: "00000000-0000-0000-0000-000000000103",
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

const tradeWire = {
  id: "00000000-0000-0000-0000-000000000333",
  symbol: "BTCUSDT",
  direction: "long",
  horizon: "short_term",
  labels: ["manual"],
  linkedReportId: null,
  leverage: "2",
  legs: [
    {
      id: "00000000-0000-0000-0000-000000000101",
      action: "open",
      executedAt: "2026-07-31T12:00:00Z",
      price: "100",
      quantity: "1",
      fee: "0.1",
    },
    {
      id: "00000000-0000-0000-0000-000000000102",
      action: "close",
      executedAt: "2026-07-31T13:00:00Z",
      price: "120",
      quantity: "1",
      fee: "0.2",
    },
  ],
  cashflows: [
    {
      id: "00000000-0000-0000-0000-000000000103",
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
