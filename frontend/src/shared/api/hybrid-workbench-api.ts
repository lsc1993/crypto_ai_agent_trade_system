import type {
  AnalyticsFilters,
  AnalyticsSnapshot,
} from "../../domain/analytics";
import {
  dashboardSnapshotSchema,
  type DashboardSnapshot,
  type MarketDetail,
  type MarketSummary,
} from "../../domain/market";
import type { Page, Symbol, Timeframe } from "../../domain/primitives";
import type {
  AnalysisReport,
  AnalysisReportSummary,
  AnalysisStreamEvent,
  ReportFilters,
} from "../../domain/report";
import type {
  Trade,
  TradeDraft,
  TradeFilters,
} from "../../domain/trade";
import { MockWorkbenchApi } from "./mock-workbench-api";
import type { ReportRunCreated, WorkbenchApi } from "./workbench-api";

export interface RemoteWorkbenchApi {
  listMarketSummaries(): Promise<MarketSummary[]>;
  getMarket(input: {
    symbol: Symbol;
    timeframes: Timeframe[];
  }): Promise<MarketDetail>;
  listReports(
    filters: ReportFilters,
  ): Promise<Page<AnalysisReportSummary>>;
  getReport(reportId: string): Promise<AnalysisReport>;
  startReport(input: { symbol: Symbol }): Promise<ReportRunCreated>;
  retryReport(reportId: string): Promise<ReportRunCreated>;
  subscribeReport(
    analysisId: string,
    onEvent: (event: AnalysisStreamEvent) => void,
  ): () => void;
  listTrades(filters: TradeFilters): Promise<Page<Trade>>;
  createTrade(draft: TradeDraft): Promise<Trade>;
  updateTrade(tradeId: string, draft: TradeDraft): Promise<Trade>;
  getAnalytics(filters: AnalyticsFilters): Promise<AnalyticsSnapshot>;
}

export class HybridWorkbenchApi implements WorkbenchApi {
  constructor(
    private readonly mockApi: MockWorkbenchApi,
    private readonly remoteApi: RemoteWorkbenchApi,
  ) {}

  async getDashboard(): Promise<DashboardSnapshot> {
    const [mockDashboard, markets, reports] = await Promise.all([
      this.mockApi.getDashboard(),
      this.remoteApi.listMarketSummaries(),
      this.remoteApi.listReports({ page: 1, pageSize: 20 }),
    ]);
    const generatedAt = markets.reduce(
      (latest, market) =>
        market.freshness.fetchedAt > latest
          ? market.freshness.fetchedAt
          : latest,
      mockDashboard.generatedAt,
    );
    return dashboardSnapshotSchema.parse({
      ...mockDashboard,
      generatedAt,
      markets,
      recentReports: reports.items,
    });
  }

  getMarket(input: {
    symbol: Symbol;
    timeframes: Timeframe[];
  }): Promise<MarketDetail> {
    return this.remoteApi.getMarket(input);
  }

  listReports(
    filters: ReportFilters,
  ): Promise<Page<AnalysisReportSummary>> {
    return this.remoteApi.listReports(filters);
  }

  getReport(reportId: string): Promise<AnalysisReport> {
    return this.remoteApi.getReport(reportId);
  }

  startReport(input: { symbol: Symbol }): Promise<ReportRunCreated> {
    return this.remoteApi.startReport(input);
  }

  retryReport(reportId: string): Promise<ReportRunCreated> {
    return this.remoteApi.retryReport(reportId);
  }

  subscribeReport(
    analysisId: string,
    onEvent: (event: AnalysisStreamEvent) => void,
  ): () => void {
    return this.remoteApi.subscribeReport(analysisId, onEvent);
  }

  listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    return this.remoteApi.listTrades(filters);
  }

  createTrade(draft: TradeDraft): Promise<Trade> {
    return this.remoteApi.createTrade(draft);
  }

  updateTrade(tradeId: string, draft: TradeDraft): Promise<Trade> {
    return this.remoteApi.updateTrade(tradeId, draft);
  }

  getAnalytics(filters: AnalyticsFilters): Promise<AnalyticsSnapshot> {
    return this.remoteApi.getAnalytics(filters);
  }
}
