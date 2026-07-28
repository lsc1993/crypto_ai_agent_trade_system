import { describe, expect, it } from "vitest";

import type { MarketDetail, MarketSummary } from "../../domain/market";
import { WorkbenchHttpError } from "./http-transport";
import { HybridWorkbenchApi, type MarketDataApi } from "./hybrid-workbench-api";
import { MockWorkbenchApi } from "./mock-workbench-api";

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
  series: [],
  news: [],
};

function marketApi(
  summaries: () => Promise<MarketSummary[]>,
): MarketDataApi {
  return {
    listMarketSummaries: summaries,
    getMarket: () => Promise.resolve(liveDetail),
  };
}

describe("HybridWorkbenchApi", () => {
  it("replaces only Mock market cards and preserves Mock research content", async () => {
    const mockApi = new MockWorkbenchApi();
    const original = await mockApi.getDashboard();
    const api = new HybridWorkbenchApi(
      mockApi,
      marketApi(() => Promise.resolve([liveSummary])),
    );

    const dashboard = await api.getDashboard();

    expect(dashboard.markets).toEqual([liveSummary]);
    expect(dashboard.news).toEqual(original.news);
    expect(dashboard.recentReports).toEqual(original.recentReports);
    expect(dashboard.generatedAt).toBe("2026-07-28T12:00:00Z");
  });

  it("propagates an unavailable public provider instead of falling back to Mock market data", async () => {
    const unavailable = new WorkbenchHttpError(
      503,
      "market_data_unavailable",
      "公开行情服务不可用",
    );
    const api = new HybridWorkbenchApi(
      new MockWorkbenchApi(),
      marketApi(async () => Promise.reject(unavailable)),
    );

    await expect(api.getDashboard()).rejects.toBe(unavailable);
  });
});
