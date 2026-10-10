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
import type {
  BacktestFilters,
  BacktestRequest,
  BacktestRunDetail,
  BacktestRunSummary,
} from "../../domain/backtest";
import type { Page, Symbol, Timeframe } from "../../domain/primitives";
import type { ResearchSymbolEntry } from "../../domain/research-symbol";
import type { TechnicalReport, TechnicalReportFilters, TechnicalRun } from "../../domain/technical-report";
import type {
  ManualPaperIntent,
  PaperAccountCreate,
  PaperAccountDetail,
  PaperAccountFilters,
  PaperAccountSummary,
  PaperPerformanceSnapshot,
} from "../../domain/paper-trading";
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
  listResearchSymbols?(): Promise<ResearchSymbolEntry[]>;
  addResearchSymbol?(input: {
    symbol: string;
    keywords?: string[];
  }): Promise<ResearchSymbolEntry>;
  archiveResearchSymbol?(symbol: Symbol): Promise<ResearchSymbolEntry>;
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
  startTechnicalReport(input: { symbol: Symbol }): Promise<TechnicalReport>;
  startTechnicalReportRun(input: { symbol: Symbol; requestId: string }): Promise<TechnicalRun>;
  getTechnicalReportRun(runId: string): Promise<TechnicalRun>;
  listTechnicalReports(filters: TechnicalReportFilters): Promise<Page<TechnicalReport>>;
  getTechnicalReport(reportId: string): Promise<TechnicalReport>;
  subscribeReport(
    analysisId: string,
    onEvent: (event: AnalysisStreamEvent) => void,
  ): () => void;
  listTrades(filters: TradeFilters): Promise<Page<Trade>>;
  createTrade(draft: TradeDraft): Promise<Trade>;
  updateTrade(tradeId: string, draft: TradeDraft): Promise<Trade>;
  getAnalytics(filters: AnalyticsFilters): Promise<AnalyticsSnapshot>;
  startBacktest(input: BacktestRequest): Promise<BacktestRunDetail>;
  listBacktests(
    filters: BacktestFilters,
  ): Promise<Page<BacktestRunSummary>>;
  getBacktest(backtestId: string): Promise<BacktestRunDetail>;
  createPaperAccount(input: PaperAccountCreate): Promise<PaperAccountDetail>;
  listPaperAccounts(
    filters: PaperAccountFilters,
  ): Promise<Page<PaperAccountSummary>>;
  getPaperAccount(accountId: string): Promise<PaperAccountDetail>;
  getPaperPerformance(accountId: string): Promise<PaperPerformanceSnapshot>;
  submitPaperManualIntent(
    accountId: string,
    input: ManualPaperIntent,
  ): Promise<PaperAccountDetail>;
  evaluatePaperStrategy(accountId: string): Promise<PaperAccountDetail>;
  archivePaperAccount(accountId: string): Promise<PaperAccountDetail>;
}

export class HybridWorkbenchApi implements WorkbenchApi {
  constructor(
    private readonly mockApi: MockWorkbenchApi,
    private readonly remoteApi: RemoteWorkbenchApi,
  ) {}

  listResearchSymbols(): Promise<ResearchSymbolEntry[]> {
    return this.remoteApi.listResearchSymbols?.() ?? this.mockApi.listResearchSymbols();
  }

  addResearchSymbol(input: {
    symbol: string;
    keywords?: string[];
  }): Promise<ResearchSymbolEntry> {
    return this.remoteApi.addResearchSymbol?.(input) ?? this.mockApi.addResearchSymbol(input);
  }

  archiveResearchSymbol(symbol: Symbol): Promise<ResearchSymbolEntry> {
    return this.remoteApi.archiveResearchSymbol?.(symbol) ?? this.mockApi.archiveResearchSymbol(symbol);
  }

  async getDashboard(input?: { symbol: Symbol }): Promise<DashboardSnapshot> {
    const [mockDashboard, markets, reports] = await Promise.all([
      this.mockApi.getDashboard(input),
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

  startTechnicalReport(input: { symbol: Symbol }): Promise<TechnicalReport> {
    return this.remoteApi.startTechnicalReport(input);
  }

  startTechnicalReportRun(input: {symbol: Symbol; requestId: string}): Promise<TechnicalRun> {
    return this.remoteApi.startTechnicalReportRun(input);
  }

  getTechnicalReportRun(runId: string): Promise<TechnicalRun> {
    return this.remoteApi.getTechnicalReportRun(runId);
  }

  listTechnicalReports(filters: TechnicalReportFilters): Promise<Page<TechnicalReport>> {
    return this.remoteApi.listTechnicalReports(filters);
  }

  getTechnicalReport(reportId: string): Promise<TechnicalReport> {
    return this.remoteApi.getTechnicalReport(reportId);
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

  startBacktest(input: BacktestRequest): Promise<BacktestRunDetail> {
    return this.remoteApi.startBacktest(input);
  }

  listBacktests(
    filters: BacktestFilters,
  ): Promise<Page<BacktestRunSummary>> {
    return this.remoteApi.listBacktests(filters);
  }

  getBacktest(backtestId: string): Promise<BacktestRunDetail> {
    return this.remoteApi.getBacktest(backtestId);
  }

  createPaperAccount(input: PaperAccountCreate): Promise<PaperAccountDetail> {
    return this.remoteApi.createPaperAccount(input);
  }

  listPaperAccounts(
    filters: PaperAccountFilters,
  ): Promise<Page<PaperAccountSummary>> {
    return this.remoteApi.listPaperAccounts(filters);
  }

  getPaperAccount(accountId: string): Promise<PaperAccountDetail> {
    return this.remoteApi.getPaperAccount(accountId);
  }

  getPaperPerformance(accountId: string): Promise<PaperPerformanceSnapshot> {
    return this.remoteApi.getPaperPerformance(accountId);
  }

  submitPaperManualIntent(
    accountId: string,
    input: ManualPaperIntent,
  ): Promise<PaperAccountDetail> {
    return this.remoteApi.submitPaperManualIntent(accountId, input);
  }

  evaluatePaperStrategy(accountId: string): Promise<PaperAccountDetail> {
    return this.remoteApi.evaluatePaperStrategy(accountId);
  }

  archivePaperAccount(accountId: string): Promise<PaperAccountDetail> {
    return this.remoteApi.archivePaperAccount(accountId);
  }
}
