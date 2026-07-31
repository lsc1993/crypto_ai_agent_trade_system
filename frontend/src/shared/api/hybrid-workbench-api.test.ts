import { describe, expect, it, vi } from "vitest";

import type { MarketDetail, MarketSummary } from "../../domain/market";
import type { Page, Symbol } from "../../domain/primitives";
import type {
  AnalysisReport,
  AnalysisReportSummary,
} from "../../domain/report";
import { WorkbenchHttpError } from "./http-transport";
import {
  HybridWorkbenchApi,
  type MarketAndReportApi,
} from "./hybrid-workbench-api";
import { MockWorkbenchApi } from "./mock-workbench-api";
import type { ReportRunCreated } from "./workbench-api";

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

const realReportSummary: AnalysisReportSummary = {
  id: "report-real-001",
  analysisId: "analysis-real-001",
  symbol: "BTCUSDT",
  status: "completed",
  title: "BTCUSDT 真实市场研究",
  summary: "来自本地 API 的持久化报告。",
  createdAt: "2026-07-31T08:00:00Z",
  dataCutoffAt: "2026-07-31T07:55:00Z",
};

const realReport: AnalysisReport = {
  ...realReportSummary,
  facts: ["BTCUSDT 公开行情已写入研究数据集。"],
  inferences: ["报告由确定性研究流程生成。"],
  risks: [],
  limitations: [],
  evidence: [],
};

const realReportPage: Page<AnalysisReportSummary> = {
  items: [realReportSummary],
  page: 1,
  pageSize: 20,
  total: 1,
};

const realReportRun: ReportRunCreated = {
  analysisId: "analysis-real-002",
  reportId: "report-real-002",
};

function unexpected<T>(operation: string): () => Promise<T> {
  return () => Promise.reject(new Error(`Unexpected remote ${operation} call`));
}

function remoteApi(
  overrides: Partial<MarketAndReportApi>,
): MarketAndReportApi {
  return {
    listMarketSummaries: unexpected<MarketSummary[]>("listMarketSummaries"),
    getMarket: unexpected<MarketDetail>("getMarket"),
    listReports: unexpected<Page<AnalysisReportSummary>>("listReports"),
    getReport: unexpected<AnalysisReport>("getReport"),
    startReport: unexpected<ReportRunCreated>("startReport"),
    retryReport: unexpected<ReportRunCreated>("retryReport"),
    subscribeReport: () => {
      throw new Error("Unexpected remote subscribeReport call");
    },
    ...overrides,
  };
}

describe("HybridWorkbenchApi", () => {
  it("combines real market cards and reports with Mock news", async () => {
    const mockApi = new MockWorkbenchApi();
    const original = await mockApi.getDashboard();
    const listReports = vi.fn(() => Promise.resolve(realReportPage));
    const api = new HybridWorkbenchApi(
      mockApi,
      remoteApi({
        listMarketSummaries: () => Promise.resolve([liveSummary]),
        listReports,
      }),
    );

    const dashboard = await api.getDashboard();

    expect(dashboard.markets).toEqual([liveSummary]);
    expect(dashboard.news).toEqual(original.news);
    expect(dashboard.recentReports).toEqual([realReportSummary]);
    expect(dashboard.generatedAt).toBe("2026-07-28T12:00:00Z");
    expect(listReports).toHaveBeenCalledWith({ page: 1, pageSize: 20 });
  });

  it("propagates an unavailable public provider instead of falling back to Mock market data", async () => {
    const unavailable = new WorkbenchHttpError(
      503,
      "market_data_unavailable",
      "公开行情服务不可用",
    );
    const api = new HybridWorkbenchApi(
      new MockWorkbenchApi(),
      remoteApi({
        listMarketSummaries: async () => Promise.reject(unavailable),
        listReports: () => Promise.resolve(realReportPage),
      }),
    );

    await expect(api.getDashboard()).rejects.toBe(unavailable);
  });

  it("propagates a rejected real report list instead of returning Mock reports", async () => {
    const unavailable = new WorkbenchHttpError(
      503,
      "analysis_reports_unavailable",
      "分析报告服务不可用",
    );
    const api = new HybridWorkbenchApi(
      new MockWorkbenchApi(),
      remoteApi({
        listMarketSummaries: () => Promise.resolve([liveSummary]),
        listReports: async () => Promise.reject(unavailable),
      }),
    );

    await expect(api.getDashboard()).rejects.toBe(unavailable);
  });

  it("delegates report listing to the real API", async () => {
    const listReports = vi.fn(() => Promise.resolve(realReportPage));
    const api = new HybridWorkbenchApi(
      new MockWorkbenchApi(),
      remoteApi({ listReports }),
    );
    const filters = { page: 2, pageSize: 5, symbol: "BTCUSDT" as Symbol };

    await expect(api.listReports(filters)).resolves.toEqual(realReportPage);
    expect(listReports).toHaveBeenCalledWith(filters);
  });

  it("delegates report detail reads to the real API", async () => {
    const getReport = vi.fn(() => Promise.resolve(realReport));
    const api = new HybridWorkbenchApi(
      new MockWorkbenchApi(),
      remoteApi({ getReport }),
    );

    await expect(api.getReport(realReport.id)).resolves.toEqual(realReport);
    expect(getReport).toHaveBeenCalledWith(realReport.id);
  });

  it("delegates report creation to the real API", async () => {
    const startReport = vi.fn(() => Promise.resolve(realReportRun));
    const api = new HybridWorkbenchApi(
      new MockWorkbenchApi(),
      remoteApi({ startReport }),
    );

    await expect(api.startReport({ symbol: "BTCUSDT" })).resolves.toEqual(
      realReportRun,
    );
    expect(startReport).toHaveBeenCalledWith({ symbol: "BTCUSDT" });
  });

  it("delegates report retry to the real API", async () => {
    const retryReport = vi.fn(() => Promise.resolve(realReportRun));
    const api = new HybridWorkbenchApi(
      new MockWorkbenchApi(),
      remoteApi({ retryReport }),
    );

    await expect(api.retryReport(realReport.id)).resolves.toEqual(realReportRun);
    expect(retryReport).toHaveBeenCalledWith(realReport.id);
  });

  it("delegates report event subscriptions to the real API", () => {
    const unsubscribe = vi.fn();
    const onEvent = vi.fn();
    const subscribeReport = vi.fn(() => unsubscribe);
    const api = new HybridWorkbenchApi(
      new MockWorkbenchApi(),
      remoteApi({ subscribeReport }),
    );

    expect(api.subscribeReport(realReport.analysisId, onEvent)).toBe(unsubscribe);
    expect(subscribeReport).toHaveBeenCalledWith(realReport.analysisId, onEvent);
  });
});
