import { describe, expect, it, vi } from "vitest";

import type {
  BacktestFilters,
  BacktestRequest,
  BacktestRunDetail,
  BacktestRunSummary,
} from "../../domain/backtest";
import type { MarketDetail, MarketSummary } from "../../domain/market";
import type {
  PaperAccountDetail,
  PaperAccountSummary,
  PaperPerformanceSnapshot,
} from "../../domain/paper-trading";
import type { Page, Symbol } from "../../domain/primitives";
import type {
  AnalysisReport,
  AnalysisReportSummary,
} from "../../domain/report";
import type { AnalyticsSnapshot } from "../../domain/analytics";
import type { Trade } from "../../domain/trade";
import { WorkbenchHttpError } from "./http-transport";
import {
  HybridWorkbenchApi,
  type RemoteWorkbenchApi,
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
  generatorKind: "deterministic",
};

const realReport: AnalysisReport = {
  ...realReportSummary,
  generatedAt: "2026-07-31T08:00:00Z",
  facts: ["BTCUSDT 公开行情已写入研究数据集。"],
  inferences: ["报告由确定性研究流程生成。"],
  risks: [],
  limitations: [],
  evidence: [],
  agentAnalysis: null,
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
  overrides: Partial<RemoteWorkbenchApi>,
): RemoteWorkbenchApi {
  return {
    listMarketSummaries: unexpected<MarketSummary[]>("listMarketSummaries"),
    getMarket: unexpected<MarketDetail>("getMarket"),
    listReports: unexpected<Page<AnalysisReportSummary>>("listReports"),
    getReport: unexpected<AnalysisReport>("getReport"),
    startReport: unexpected<ReportRunCreated>("startReport"),
    retryReport: unexpected<ReportRunCreated>("retryReport"),
    startTechnicalReport: () => Promise.reject(new Error("unexpected technical report")),
    listTechnicalReports: () => Promise.reject(new Error("unexpected technical reports")),
    getTechnicalReport: () => Promise.reject(new Error("unexpected technical report")),
    subscribeReport: () => {
      throw new Error("Unexpected remote subscribeReport call");
    },
    listTrades: () => unexpected<Page<Trade>>("listTrades")(),
    createTrade: () => unexpected<Trade>("createTrade")(),
    updateTrade: () => unexpected<Trade>("updateTrade")(),
    getAnalytics: () => unexpected<AnalyticsSnapshot>("getAnalytics")(),
    startBacktest: () => unexpected<BacktestRunDetail>("startBacktest")(),
    listBacktests: () => unexpected<Page<BacktestRunSummary>>("listBacktests")(),
    getBacktest: () => unexpected<BacktestRunDetail>("getBacktest")(),
    createPaperAccount: () =>
      unexpected<PaperAccountDetail>("createPaperAccount")(),
    listPaperAccounts: () =>
      unexpected<Page<PaperAccountSummary>>("listPaperAccounts")(),
    getPaperAccount: () => unexpected<PaperAccountDetail>("getPaperAccount")(),
    getPaperPerformance: () =>
      unexpected<PaperPerformanceSnapshot>("getPaperPerformance")(),
    submitPaperManualIntent: () =>
      unexpected<PaperAccountDetail>("submitPaperManualIntent")(),
    evaluatePaperStrategy: () =>
      unexpected<PaperAccountDetail>("evaluatePaperStrategy")(),
    archivePaperAccount: () =>
      unexpected<PaperAccountDetail>("archivePaperAccount")(),
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

  it("delegates journal and analytics calls to the remote API without Mock fallback", async () => {
    const mockApi = new MockWorkbenchApi();
    const tradePage = await mockApi.listTrades({ page: 1, pageSize: 20 });
    const trade = tradePage.items[0];
    if (trade === undefined) {
      throw new Error("Mock trade fixture is missing");
    }
    const snapshot = await mockApi.getAnalytics({});
    const listTrades = vi.fn(() => Promise.resolve(tradePage));
    const createTrade = vi.fn(() => Promise.resolve(trade));
    const updateTrade = vi.fn(() => Promise.resolve(trade));
    const getAnalytics = vi.fn(() => Promise.resolve(snapshot));
    const api = new HybridWorkbenchApi(
      mockApi,
      remoteApi({ listTrades, createTrade, updateTrade, getAnalytics }),
    );

    await expect(api.listTrades({ page: 1, pageSize: 20 })).resolves.toEqual(
      tradePage,
    );
    await expect(api.createTrade(trade)).resolves.toEqual(trade);
    await expect(api.updateTrade(trade.id, trade)).resolves.toEqual(trade);
    await expect(api.getAnalytics({})).resolves.toEqual(snapshot);

    expect(listTrades).toHaveBeenCalledWith({ page: 1, pageSize: 20 });
    expect(createTrade).toHaveBeenCalledWith(trade);
    expect(updateTrade).toHaveBeenCalledWith(trade.id, trade);
    expect(getAnalytics).toHaveBeenCalledWith({});
  });

  it("propagates remote journal failures instead of returning Mock content", async () => {
    const unavailable = new WorkbenchHttpError(
      503,
      "trade_storage_unavailable",
      "交易日志存储不可用",
    );
    const api = new HybridWorkbenchApi(
      new MockWorkbenchApi(),
      remoteApi({ listTrades: async () => Promise.reject(unavailable) }),
    );

    await expect(
      api.listTrades({ page: 1, pageSize: 20 }),
    ).rejects.toBe(unavailable);
  });

  it("requires a local backend for Mock backtests and propagates remote failures", async () => {
    const request: BacktestRequest = {
      symbol: "BTCUSDT",
      timeframe: "1h",
      startAt: "2026-07-01T00:00:00Z",
      endAt: "2026-07-02T00:00:00Z",
      initialCash: "10000",
    };
    const filters: BacktestFilters = { page: 1, pageSize: 20 };
    const unavailable = new WorkbenchHttpError(
      503,
      "backtest_storage_unavailable",
      "回测存储不可用",
    );
    const api = new HybridWorkbenchApi(
      new MockWorkbenchApi(),
      remoteApi({ listBacktests: async () => Promise.reject(unavailable) }),
    );

    await expect(new MockWorkbenchApi().startBacktest(request)).rejects.toThrow(
      "策略回测需要连接本地后端",
    );
    await expect(api.listBacktests(filters)).rejects.toBe(unavailable);
  });

  it("delegates paper performance reads to the remote API without Mock fallback", async () => {
    const snapshot = paperPerformanceSnapshot();
    const getPaperPerformance = vi.fn(() => Promise.resolve(snapshot));
    const api = new HybridWorkbenchApi(
      new MockWorkbenchApi(),
      remoteApi({ getPaperPerformance }),
    );

    await expect(api.getPaperPerformance(snapshot.accountId)).resolves.toEqual(
      snapshot,
    );
    expect(getPaperPerformance).toHaveBeenCalledWith(snapshot.accountId);
  });

  it("requires the local API and database for Mock paper performance", async () => {
    await expect(
      new MockWorkbenchApi().getPaperPerformance(
        "00000000-0000-4000-8000-000000000801",
      ),
    ).rejects.toThrow("模拟盘需要本地 API 与数据库");
  });
});

function paperPerformanceSnapshot(): PaperPerformanceSnapshot {
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
    ],
    generatedAt: "2026-08-04T01:00:00Z",
  };
}
