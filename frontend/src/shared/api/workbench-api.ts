import type {
  AnalyticsFilters,
  AnalyticsSnapshot,
} from "../../domain/analytics";
import type {
  DashboardSnapshot,
  MarketDetail,
} from "../../domain/market";
import type {
  BacktestFilters,
  BacktestRequest,
  BacktestRunDetail,
  BacktestRunSummary,
} from "../../domain/backtest";
import type { Page, Symbol, Timeframe } from "../../domain/primitives";
import type { ResearchSymbolEntry } from "../../domain/research-symbol";
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

export interface ReportRunCreated {
  analysisId: string;
  reportId?: string;
}

export interface WorkbenchApi {
  listResearchSymbols(): Promise<ResearchSymbolEntry[]>;
  addResearchSymbol(input: {
    symbol: string;
    keywords?: string[];
  }): Promise<ResearchSymbolEntry>;
  archiveResearchSymbol(symbol: Symbol): Promise<ResearchSymbolEntry>;
  getDashboard(input?: { symbol: Symbol }): Promise<DashboardSnapshot>;
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
