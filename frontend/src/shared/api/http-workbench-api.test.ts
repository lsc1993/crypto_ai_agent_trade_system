import { describe, expect, it, vi } from "vitest";

import type { MarketDetail, MarketSummary } from "../../domain/market";
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
