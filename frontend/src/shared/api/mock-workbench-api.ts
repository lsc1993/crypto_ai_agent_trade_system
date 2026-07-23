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
  analysisReportSchema,
  analysisReportSummarySchema,
  analysisStreamEventSchema,
  reportFiltersSchema,
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
  mockAnalytics,
  mockDashboard,
  mockMarketDetails,
} from "../mocks/fixtures";
import { MOCK_STORAGE_KEY } from "../mocks/reset";
import {
  createMockSeed,
  mockStateSchema,
  type MockState,
} from "../mocks/seed";
import type { WorkbenchApi } from "./workbench-api";

const marketInputSchema = z.object({
  symbol: symbolSchema,
  timeframes: z.array(timeframeSchema).min(1),
});
const reportStartSchema = z.object({ symbol: symbolSchema });
const analysisResultSchema = z.object({ analysisId: identifierSchema });

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

export class MockWorkbenchApi implements WorkbenchApi {
  private state: MockState;

  constructor() {
    this.state = loadState();
  }

  async getDashboard(): Promise<DashboardSnapshot> {
    return Promise.resolve(dashboardSnapshotSchema.parse(mockDashboard));
  }

  async getMarket(input: {
    symbol: Symbol;
    timeframes: Timeframe[];
  }): Promise<MarketDetail> {
    const parsedInput = marketInputSchema.parse(input);
    const detail = mockMarketDetails.find(
      (candidate) => candidate.summary.symbol === parsedInput.symbol,
    );
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
      .map((report) => analysisReportSummarySchema.parse(report));
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
    reportStartSchema.parse(input);
    const analysisId = `analysis-new-${String(
      this.state.nextAnalysisSequence,
    ).padStart(4, "0")}`;
    this.state.nextAnalysisSequence += 1;
    persistState(this.state);
    return Promise.resolve(analysisResultSchema.parse({ analysisId }));
  }

  async retryReport(
    reportId: string,
  ): Promise<{ analysisId: string }> {
    await this.getReport(reportId);
    const analysisId = `analysis-retry-${String(
      this.state.nextAnalysisSequence,
    ).padStart(4, "0")}`;
    this.state.nextAnalysisSequence += 1;
    persistState(this.state);
    return analysisResultSchema.parse({ analysisId });
  }

  subscribeReport(
    analysisId: string,
    onEvent: (event: AnalysisStreamEvent) => void,
  ): () => void {
    const parsedId = identifierSchema.parse(analysisId);
    const events = [
      analysisStreamEventSchema.parse({
        analysisId: parsedId,
        symbol: "BTCUSDT",
        status: "queued",
        occurredAt: "2025-02-01T01:00:00Z",
        message: "Mock analysis queued",
      }),
      analysisStreamEventSchema.parse({
        analysisId: parsedId,
        symbol: "BTCUSDT",
        status: "running",
        occurredAt: "2025-02-01T01:00:01Z",
        message: "Mock analysis running",
      }),
      analysisStreamEventSchema.parse({
        analysisId: parsedId,
        symbol: "BTCUSDT",
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
    analyticsFiltersSchema.parse(filters);
    return Promise.resolve(analyticsSnapshotSchema.parse(mockAnalytics));
  }

  reset(): void {
    this.state = createMockSeed();
    persistState(this.state);
  }
}
