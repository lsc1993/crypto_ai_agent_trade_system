import Decimal from "decimal.js";
import { z } from "zod";

import {
  analyticsFiltersSchema,
  analyticsSnapshotSchema,
  type AnalyticsFilters,
  type AnalyticsSnapshot,
} from "../../domain/analytics";
import {
  dashboardSnapshotSchema,
  marketDetailSchema,
  type DashboardSnapshot,
  type MarketDetail,
} from "../../domain/market";
import type {
  BacktestFilters,
  BacktestRequest,
  BacktestRunDetail,
  BacktestRunSummary,
} from "../../domain/backtest";
import {
  identifierSchema,
  pageSchema,
  symbolSchema,
  timeframeSchema,
  type Page,
  type Symbol,
  type Timeframe,
} from "../../domain/primitives";
import {
  researchSymbolEntrySchema,
  type ResearchSymbolEntry,
} from "../../domain/research-symbol";
import type {
  ManualPaperIntent,
  PaperAccountCreate,
  PaperAccountDetail,
  PaperAccountFilters,
  PaperAccountSummary,
  PaperPerformanceSnapshot,
} from "../../domain/paper-trading";
import {
  analysisReportSchema,
  analysisReportSummarySchema,
  analysisStreamEventSchema,
  reportFiltersSchema,
  toAnalysisReportSummary,
  type AnalysisReport,
  type AnalysisReportSummary,
  type AnalysisStreamEvent,
  type ReportFilters,
} from "../../domain/report";
import {
  tradeDraftSchema,
  tradeFiltersSchema,
  tradeSchema,
  type Trade,
  type TradeDraft,
  type TradeFilters,
} from "../../domain/trade";
import {
  mockDashboard,
  mockMarketDetails,
  MOCK_ANALYTICS_GENERATED_AT,
} from "../mocks/fixtures";
import { MOCK_STORAGE_KEY } from "../mocks/reset";
import {
  createMockSeed,
  mockStateSchema,
  type MockState,
} from "../mocks/seed";
import type { WorkbenchApi } from "./workbench-api";
import {
  technicalReportFiltersSchema,
  technicalReportSchema,
  type TechnicalReport,
  type TechnicalReportFilters,
} from "../../domain/technical-report";

const marketInputSchema = z.object({
  symbol: symbolSchema,
  timeframes: z.array(timeframeSchema).min(1),
});
const reportStartSchema = z.object({ symbol: symbolSchema });
const analysisResultSchema = z.object({ analysisId: identifierSchema });
const BACKTEST_REQUIRES_BACKEND_MESSAGE = "策略回测需要连接本地后端";
const PAPER_TRADING_REQUIRES_BACKEND_MESSAGE = "模拟盘需要本地 API 与数据库";

export class MockWorkbenchNotFoundError extends Error {
  constructor(resource: "report" | "trade", identifier: string) {
    super(`Mock ${resource} not found: ${identifier}`);
    this.name = "MockWorkbenchNotFoundError";
  }
}

function loadState(): MockState {
  if (typeof localStorage === "undefined") {
    return createMockSeed();
  }

  const stored = localStorage.getItem(MOCK_STORAGE_KEY);
  if (stored === null) {
    return createMockSeed();
  }

  try {
    const parsed: unknown = JSON.parse(stored);
    const state = mockStateSchema.safeParse(parsed);
    return state.success ? state.data : createMockSeed();
  } catch {
    return createMockSeed();
  }
}

function persistState(state: MockState): void {
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(
      MOCK_STORAGE_KEY,
      JSON.stringify(mockStateSchema.parse(state)),
    );
  }
}

function resolveTradeStatus(draft: TradeDraft): {
  status: "open" | "closed";
  closedAt: string | null;
} {
  let remaining = new Decimal(0);
  let closedAt: string | null = null;
  for (const leg of draft.legs) {
    const quantity = new Decimal(leg.quantity);
    if (leg.action === "open") {
      remaining = remaining.plus(quantity);
    } else {
      remaining = remaining.minus(quantity);
    }
    if (leg.action === "close") {
      closedAt = leg.executedAt;
    }
  }
  return {
    status: remaining.isZero() ? "closed" : "open",
    closedAt,
  };
}

function deterministicTimestamp(sequence: number): string {
  const minute = String(sequence % 60).padStart(2, "0");
  return `2025-02-01T00:${minute}:00Z`;
}

function matchesAnalyticsFilters(
  trade: Trade,
  filters: AnalyticsFilters,
): boolean {
  return (
    (filters.symbol === undefined || trade.symbol === filters.symbol) &&
    (filters.direction === undefined ||
      trade.direction === filters.direction) &&
    (filters.horizon === undefined || trade.horizon === filters.horizon) &&
    (filters.label === undefined || trade.labels.includes(filters.label)) &&
    (filters.from === undefined ||
      Date.parse(trade.openedAt) >= Date.parse(filters.from)) &&
    (filters.to === undefined ||
      Date.parse(trade.openedAt) <= Date.parse(filters.to))
  );
}

function maximumNetPnlFractionDigits(trades: Trade[]): number {
  return trades.reduce((maximum, trade) => {
    const fraction = trade.netPnl.split(".")[1];
    return Math.max(maximum, fraction?.length ?? 0);
  }, 0);
}

function formatAnalyticsDecimal(
  value: Decimal,
  minimumFractionDigits = 0,
): string {
  const normalized = value.isZero() ? new Decimal(0) : value;
  const decimalPlaces = Math.min(
    18,
    Math.max(minimumFractionDigits, normalized.decimalPlaces() ?? 0),
  );
  return normalized.toFixed(decimalPlaces);
}

function deriveAnalyticsSnapshot(trades: Trade[]): AnalyticsSnapshot {
  const orderedTrades = trades
    .filter((trade) => trade.status === "closed" && trade.closedAt !== null)
    .sort((left, right) => {
    const timestampOrder = (left.closedAt ?? "").localeCompare(
      right.closedAt ?? "",
    );
    return timestampOrder === 0 ? left.id.localeCompare(right.id) : timestampOrder;
    });
  const minimumFractionDigits = maximumNetPnlFractionDigits(orderedTrades);
  const calendar = new Map<
    string,
    { netPnl: Decimal; tradeCount: number }
  >();
  let netPnl = new Decimal(0);
  let peakEquity = new Decimal(0);
  let maxDrawdown = new Decimal(0);
  let grossProfit = new Decimal(0);
  let grossLoss = new Decimal(0);
  let winningTrades = 0;

  const equityCurve = orderedTrades.map((trade) => {
    const tradePnl = new Decimal(trade.netPnl);
    netPnl = netPnl.plus(tradePnl);
    if (tradePnl.greaterThan(0)) {
      winningTrades += 1;
      grossProfit = grossProfit.plus(tradePnl);
    } else if (tradePnl.lessThan(0)) {
      grossLoss = grossLoss.plus(tradePnl.abs());
    }
    if (netPnl.greaterThan(peakEquity)) {
      peakEquity = netPnl;
    }
    const drawdown = netPnl.minus(peakEquity);
    if (drawdown.lessThan(maxDrawdown)) {
      maxDrawdown = drawdown;
    }

    const closedAt = trade.closedAt;
    if (closedAt === null) {
      throw new Error("Closed Mock trade must include closedAt");
    }
    const calendarAt = `${closedAt.slice(0, 10)}T00:00:00Z`;
    const calendarEntry = calendar.get(calendarAt);
    if (calendarEntry === undefined) {
      calendar.set(calendarAt, { netPnl: tradePnl, tradeCount: 1 });
    } else {
      calendarEntry.netPnl = calendarEntry.netPnl.plus(tradePnl);
      calendarEntry.tradeCount += 1;
    }

    return {
      at: closedAt,
      equity: formatAnalyticsDecimal(netPnl, minimumFractionDigits),
      netPnl: formatAnalyticsDecimal(netPnl, minimumFractionDigits),
    };
  });

  const tradeCount = orderedTrades.length;
  const winRate =
    tradeCount === 0
      ? new Decimal(0)
      : new Decimal(String(winningTrades)).div(String(tradeCount));
  const profitFactor = grossLoss.isZero() ? null : grossProfit.div(grossLoss);
  const expectancy =
    tradeCount === 0 ? new Decimal(0) : netPnl.div(String(tradeCount));

  return analyticsSnapshotSchema.parse({
    netPnl: formatAnalyticsDecimal(netPnl, minimumFractionDigits),
    winRate: formatAnalyticsDecimal(winRate),
    profitFactor:
      profitFactor === null ? null : formatAnalyticsDecimal(profitFactor),
    expectancy: formatAnalyticsDecimal(expectancy, minimumFractionDigits),
    maxDrawdown: formatAnalyticsDecimal(maxDrawdown),
    equityCurve,
    tradeCalendar: [...calendar.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([at, entry]) => ({
        at,
        netPnl: formatAnalyticsDecimal(
          entry.netPnl,
          minimumFractionDigits,
        ),
        tradeCount: entry.tradeCount,
      })),
    generatedAt: MOCK_ANALYTICS_GENERATED_AT,
  });
}

export class MockWorkbenchApi implements WorkbenchApi {
  private state: MockState;
  private technicalReports: TechnicalReport[] = [];
  private readonly researchSymbols = new Map<string, ResearchSymbolEntry>();

  constructor() {
    this.state = loadState();
    for (const symbol of ["BTCUSDT", "ETHUSDT"]) {
      this.researchSymbols.set(symbol, offlineSymbolEntry(symbol));
    }
  }

  listResearchSymbols(): Promise<ResearchSymbolEntry[]> {
    return Promise.resolve(
      [...this.researchSymbols.values()].filter((entry) => entry.enabled),
    );
  }

  addResearchSymbol(input: {
    symbol: string;
    keywords?: string[];
  }): Promise<ResearchSymbolEntry> {
    const symbol = symbolSchema.parse(input.symbol.trim().toUpperCase());
    const entry = offlineSymbolEntry(symbol, input.keywords ?? []);
    this.researchSymbols.set(symbol, entry);
    return Promise.resolve(entry);
  }

  archiveResearchSymbol(symbol: Symbol): Promise<ResearchSymbolEntry> {
    const entry = this.researchSymbols.get(symbol);
    if (entry === undefined) {
      throw new Error(`Mock research symbol not found: ${symbol}`);
    }
    const archived = researchSymbolEntrySchema.parse({
      ...entry,
      enabled: false,
      canResearch: false,
      archivedAt: "2025-02-01T00:00:00Z",
    });
    this.researchSymbols.set(symbol, archived);
    return Promise.resolve(archived);
  }

  async getDashboard(_input?: { symbol: Symbol }): Promise<DashboardSnapshot> {
    void _input;
    return Promise.resolve(dashboardSnapshotSchema.parse(mockDashboard));
  }

  async getMarket(input: {
    symbol: Symbol;
    timeframes: Timeframe[];
  }): Promise<MarketDetail> {
    const parsedInput = marketInputSchema.parse(input);
    const detail = mockMarketDetails.find(
      (candidate) => candidate.summary.symbol === parsedInput.symbol,
    ) ?? offlineMarketDetail(parsedInput.symbol);
    if (detail === undefined) {
      throw new Error(`Mock market not found: ${parsedInput.symbol}`);
    }
    const requested = new Set(parsedInput.timeframes);
    return Promise.resolve(
      marketDetailSchema.parse({
        ...detail,
        series: detail.series.filter((series) =>
          requested.has(series.timeframe),
        ),
      }),
    );
  }

  async listReports(
    filters: ReportFilters,
  ): Promise<Page<AnalysisReportSummary>> {
    const parsedFilters = reportFiltersSchema.parse(filters);
    const matching = this.state.reports
      .filter(
        (report) =>
          parsedFilters.symbol === undefined ||
          report.symbol === parsedFilters.symbol,
      )
      .filter(
        (report) =>
          parsedFilters.status === undefined ||
          report.status === parsedFilters.status,
      )
      .map((report) => toAnalysisReportSummary(report));
    const start = (parsedFilters.page - 1) * parsedFilters.pageSize;
    return Promise.resolve(
      pageSchema(analysisReportSummarySchema).parse({
        items: matching.slice(start, start + parsedFilters.pageSize),
        page: parsedFilters.page,
        pageSize: parsedFilters.pageSize,
        total: matching.length,
      }),
    );
  }

  async getReport(reportId: string): Promise<AnalysisReport> {
    const parsedId = identifierSchema.parse(reportId);
    const report = this.state.reports.find(
      (candidate) => candidate.id === parsedId,
    );
    if (report === undefined) {
      throw new MockWorkbenchNotFoundError("report", parsedId);
    }
    return Promise.resolve(analysisReportSchema.parse(report));
  }

  async startReport(input: {
    symbol: Symbol;
  }): Promise<{ analysisId: string }> {
    const parsedInput = reportStartSchema.parse(input);
    const analysisId = `analysis-new-${String(
      this.state.nextAnalysisSequence,
    ).padStart(4, "0")}`;
    this.state.analysisSymbols[analysisId] = parsedInput.symbol;
    this.state.nextAnalysisSequence += 1;
    persistState(this.state);
    return Promise.resolve(analysisResultSchema.parse({ analysisId }));
  }

  async retryReport(
    reportId: string,
  ): Promise<{ analysisId: string }> {
    const report = await this.getReport(reportId);
    const analysisId = `analysis-retry-${String(
      this.state.nextAnalysisSequence,
    ).padStart(4, "0")}`;
    this.state.analysisSymbols[analysisId] = report.symbol;
    this.state.nextAnalysisSequence += 1;
    persistState(this.state);
    return analysisResultSchema.parse({ analysisId });
  }

  async startTechnicalReport(input: { symbol: Symbol }): Promise<TechnicalReport> {
    await Promise.resolve();
    const symbol = symbolSchema.parse(input.symbol);
    const entry = this.researchSymbols.get(symbol);
    if (entry === undefined || !entry.canResearch) {
      throw new Error("当前币对不可生成技术报告");
    }
    const now = new Date().toISOString();
    const report = technicalReportSchema.parse({
      version: "technical-v1",
      id: crypto.randomUUID(),
      analysisId: crypto.randomUUID(),
      symbol,
      status: "degraded",
      createdAt: now,
      dataCutoffAt: now,
      analysis: {
        quality: { status: "invalid", reasons: ["mock_demo_only"], candleCounts: {}, latestClosedAt: {} },
        facts: null,
        plans: [],
        noPlanReasons: ["mock_demo_only"],
        methods: [],
        evidenceId: crypto.randomUUID(),
      },
      narrative: null,
      errorCode: "data_quality_insufficient",
    });
    this.technicalReports.unshift(report);
    return report;
  }

  async listTechnicalReports(filters: TechnicalReportFilters): Promise<Page<TechnicalReport>> {
    await Promise.resolve();
    const parsed = technicalReportFiltersSchema.parse(filters);
    const matching = this.technicalReports.filter((report) => parsed.symbol === undefined || report.symbol === parsed.symbol);
    const first = (parsed.page - 1) * parsed.pageSize;
    return { items: matching.slice(first, first + parsed.pageSize), page: parsed.page, pageSize: parsed.pageSize, total: matching.length };
  }

  async getTechnicalReport(reportId: string): Promise<TechnicalReport> {
    await Promise.resolve();
    const id = z.uuid().parse(reportId);
    const report = this.technicalReports.find((candidate) => candidate.id === id);
    if (report === undefined) throw new MockWorkbenchNotFoundError("report", id);
    return report;
  }

  subscribeReport(
    analysisId: string,
    onEvent: (event: AnalysisStreamEvent) => void,
  ): () => void {
    const parsedId = identifierSchema.parse(analysisId);
    const symbol = this.state.analysisSymbols[parsedId] ?? "BTCUSDT";
    const events = [
      analysisStreamEventSchema.parse({
        analysisId: parsedId,
        symbol,
        status: "queued",
        occurredAt: "2025-02-01T01:00:00Z",
        message: "Mock analysis queued",
      }),
      analysisStreamEventSchema.parse({
        analysisId: parsedId,
        symbol,
        status: "running",
        occurredAt: "2025-02-01T01:00:01Z",
        message: "Mock analysis running",
      }),
      analysisStreamEventSchema.parse({
        analysisId: parsedId,
        symbol,
        status: "completed",
        occurredAt: "2025-02-01T01:00:02Z",
        message: "Mock analysis completed",
      }),
    ];
    const timers = events.map((event, index) =>
      globalThis.setTimeout(() => {
        onEvent(event);
      }, index * 20),
    );
    return () => {
      for (const timer of timers) {
        globalThis.clearTimeout(timer);
      }
    };
  }

  async listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    const parsedFilters = tradeFiltersSchema.parse(filters);
    const matching = this.state.trades
      .filter(
        (trade) =>
          parsedFilters.symbol === undefined ||
          trade.symbol === parsedFilters.symbol,
      )
      .filter(
        (trade) =>
          parsedFilters.direction === undefined ||
          trade.direction === parsedFilters.direction,
      )
      .filter(
        (trade) =>
          parsedFilters.horizon === undefined ||
          trade.horizon === parsedFilters.horizon,
      )
      .filter(
        (trade) =>
          parsedFilters.status === undefined ||
          trade.status === parsedFilters.status,
      )
      .filter(
        (trade) =>
          parsedFilters.label === undefined ||
          trade.labels.includes(parsedFilters.label),
      )
      .filter(
        (trade) =>
          parsedFilters.from === undefined ||
          Date.parse(trade.openedAt) >= Date.parse(parsedFilters.from),
      )
      .filter(
        (trade) =>
          parsedFilters.to === undefined ||
          Date.parse(trade.openedAt) <= Date.parse(parsedFilters.to),
      );
    const start = (parsedFilters.page - 1) * parsedFilters.pageSize;
    return Promise.resolve(
      pageSchema(tradeSchema).parse({
        items: matching.slice(start, start + parsedFilters.pageSize),
        page: parsedFilters.page,
        pageSize: parsedFilters.pageSize,
        total: matching.length,
      }),
    );
  }

  createTrade(draft: TradeDraft): Promise<Trade> {
    const parsedDraft = tradeDraftSchema.parse(draft);
    const sequence = this.state.nextTradeSequence;
    const status = resolveTradeStatus(parsedDraft);
    const timestamp = deterministicTimestamp(sequence);
    const firstLeg = parsedDraft.legs[0];
    if (firstLeg === undefined) {
      throw new Error("A trade requires at least one leg");
    }
    const trade = tradeSchema.parse({
      ...parsedDraft,
      id: `trade-${String(sequence).padStart(3, "0")}`,
      status: status.status,
      netPnl: "0",
      openedAt: firstLeg.executedAt,
      closedAt: status.closedAt,
      createdAt: timestamp,
      updatedAt: timestamp,
    });
    this.state.trades.push(trade);
    this.state.nextTradeSequence += 1;
    persistState(this.state);
    return Promise.resolve(trade);
  }

  updateTrade(
    tradeId: string,
    draft: TradeDraft,
  ): Promise<Trade> {
    const parsedId = identifierSchema.parse(tradeId);
    const parsedDraft = tradeDraftSchema.parse(draft);
    const index = this.state.trades.findIndex(
      (candidate) => candidate.id === parsedId,
    );
    if (index < 0) {
      throw new MockWorkbenchNotFoundError("trade", parsedId);
    }
    const existing = this.state.trades[index];
    const firstLeg = parsedDraft.legs[0];
    if (existing === undefined || firstLeg === undefined) {
      throw new MockWorkbenchNotFoundError("trade", parsedId);
    }
    const status = resolveTradeStatus(parsedDraft);
    const updated = tradeSchema.parse({
      ...parsedDraft,
      id: existing.id,
      status: status.status,
      netPnl: existing.netPnl,
      openedAt: firstLeg.executedAt,
      closedAt: status.closedAt,
      createdAt: existing.createdAt,
      updatedAt: deterministicTimestamp(this.state.nextTradeSequence),
    });
    this.state.trades[index] = updated;
    this.state.nextTradeSequence += 1;
    persistState(this.state);
    return Promise.resolve(updated);
  }

  async getAnalytics(
    filters: AnalyticsFilters,
  ): Promise<AnalyticsSnapshot> {
    const parsedFilters = analyticsFiltersSchema.parse(filters);
    const matchingTrades = this.state.trades.filter((trade) =>
      matchesAnalyticsFilters(trade, parsedFilters),
    );
    return Promise.resolve(deriveAnalyticsSnapshot(matchingTrades));
  }

  startBacktest(_input: BacktestRequest): Promise<BacktestRunDetail> {
    void _input;
    return Promise.reject(new Error(BACKTEST_REQUIRES_BACKEND_MESSAGE));
  }

  listBacktests(
    _filters: BacktestFilters,
  ): Promise<Page<BacktestRunSummary>> {
    void _filters;
    return Promise.reject(new Error(BACKTEST_REQUIRES_BACKEND_MESSAGE));
  }

  getBacktest(_backtestId: string): Promise<BacktestRunDetail> {
    void _backtestId;
    return Promise.reject(new Error(BACKTEST_REQUIRES_BACKEND_MESSAGE));
  }

  createPaperAccount(_input: PaperAccountCreate): Promise<PaperAccountDetail> {
    void _input;
    return Promise.reject(new Error(PAPER_TRADING_REQUIRES_BACKEND_MESSAGE));
  }

  listPaperAccounts(
    _filters: PaperAccountFilters,
  ): Promise<Page<PaperAccountSummary>> {
    void _filters;
    return Promise.reject(new Error(PAPER_TRADING_REQUIRES_BACKEND_MESSAGE));
  }

  getPaperAccount(_accountId: string): Promise<PaperAccountDetail> {
    void _accountId;
    return Promise.reject(new Error(PAPER_TRADING_REQUIRES_BACKEND_MESSAGE));
  }

  getPaperPerformance(_accountId: string): Promise<PaperPerformanceSnapshot> {
    void _accountId;
    return Promise.reject(new Error(PAPER_TRADING_REQUIRES_BACKEND_MESSAGE));
  }

  submitPaperManualIntent(
    _accountId: string,
    _input: ManualPaperIntent,
  ): Promise<PaperAccountDetail> {
    void _accountId;
    void _input;
    return Promise.reject(new Error(PAPER_TRADING_REQUIRES_BACKEND_MESSAGE));
  }

  evaluatePaperStrategy(_accountId: string): Promise<PaperAccountDetail> {
    void _accountId;
    return Promise.reject(new Error(PAPER_TRADING_REQUIRES_BACKEND_MESSAGE));
  }

  archivePaperAccount(_accountId: string): Promise<PaperAccountDetail> {
    void _accountId;
    return Promise.reject(new Error(PAPER_TRADING_REQUIRES_BACKEND_MESSAGE));
  }

  reset(): void {
    this.state = createMockSeed();
    this.technicalReports = [];
    persistState(this.state);
  }
}

function offlineSymbolEntry(
  symbol: Symbol,
  keywords: string[] = [],
): ResearchSymbolEntry {
  const baseAsset = symbol.slice(0, -4);
  return researchSymbolEntrySchema.parse({
    symbol,
    baseAsset,
    quoteAsset: "USDT",
    marginAsset: "USDT",
    contractType: "PERPETUAL",
    enabled: true,
    keywords,
    capabilities: [
      { name: "market", status: "supported", message: "离线示例行情可用。" },
      { name: "candles", status: "supported", message: "离线示例 K 线可用。" },
      { name: "derivatives", status: "supported", message: "离线示例衍生品指标可用。" },
      { name: "funding", status: "supported", message: "离线示例资金费率可用。" },
      { name: "news", status: "supported", message: "离线示例资讯可用。" },
      { name: "sentiment", status: "supported", message: "离线示例情绪数据可用。" },
      { name: "etf", status: "unsupported", message: "当前数据源不支持" },
    ],
    version: 1,
    createdAt: "2025-02-01T00:00:00Z",
    archivedAt: null,
    canResearch: true,
    lastSync: { id: `offline-${symbol}`, status: "partial" },
  });
}

function offlineMarketDetail(symbol: Symbol): MarketDetail | undefined {
  const btc = mockMarketDetails.find(
    (candidate) => candidate.summary.symbol === "BTCUSDT",
  );
  if (btc === undefined) {
    return undefined;
  }
  return marketDetailSchema.parse({
    ...btc,
    summary: { ...btc.summary, symbol },
    series: btc.series.map((series) => ({
      ...series,
      candles: series.candles.map((candle) => ({ ...candle, symbol })),
    })),
  });
}
