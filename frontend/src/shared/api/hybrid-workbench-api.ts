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
import type { WorkbenchApi } from "./workbench-api";

export interface MarketDataApi {
  listMarketSummaries(): Promise<MarketSummary[]>;
  getMarket(input: {
    symbol: Symbol;
    timeframes: Timeframe[];
  }): Promise<MarketDetail>;
}

export class HybridWorkbenchApi implements WorkbenchApi {
  constructor(
    private readonly mockApi: MockWorkbenchApi,
    private readonly marketApi: MarketDataApi,
  ) {}

  async getDashboard(): Promise<DashboardSnapshot> {
    const [mockDashboard, markets] = await Promise.all([
      this.mockApi.getDashboard(),
      this.marketApi.listMarketSummaries(),
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
    });
  }

  getMarket(input: {
    symbol: Symbol;
    timeframes: Timeframe[];
  }): Promise<MarketDetail> {
    return this.marketApi.getMarket(input);
  }

  listReports(
    filters: ReportFilters,
  ): Promise<Page<AnalysisReportSummary>> {
    return this.mockApi.listReports(filters);
  }

  getReport(reportId: string): Promise<AnalysisReport> {
    return this.mockApi.getReport(reportId);
  }

  startReport(input: { symbol: Symbol }): Promise<{ analysisId: string }> {
    return this.mockApi.startReport(input);
  }

  retryReport(reportId: string): Promise<{ analysisId: string }> {
    return this.mockApi.retryReport(reportId);
  }

  subscribeReport(
    analysisId: string,
    onEvent: (event: AnalysisStreamEvent) => void,
  ): () => void {
    return this.mockApi.subscribeReport(analysisId, onEvent);
  }

  listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    return this.mockApi.listTrades(filters);
  }

  createTrade(draft: TradeDraft): Promise<Trade> {
    return this.mockApi.createTrade(draft);
  }

  updateTrade(tradeId: string, draft: TradeDraft): Promise<Trade> {
    return this.mockApi.updateTrade(tradeId, draft);
  }

  getAnalytics(filters: AnalyticsFilters): Promise<AnalyticsSnapshot> {
    return this.mockApi.getAnalytics(filters);
  }
}
