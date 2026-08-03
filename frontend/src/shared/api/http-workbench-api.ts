import {
  analysisReportSchema,
  analysisReportSummarySchema,
  reportFiltersSchema,
  type AnalysisReport,
  type AnalysisReportSummary,
  type AnalysisStreamEvent,
  type ReportFilters,
} from "../../domain/report";
import {
  identifierSchema,
  type Page,
  type Symbol,
  type Timeframe,
} from "../../domain/primitives";
import type {
  AnalyticsFilters,
  AnalyticsSnapshot,
} from "../../domain/analytics";
import {
  analyticsFiltersSchema,
  analyticsSnapshotSchema,
} from "../../domain/analytics";
import type {
  DashboardSnapshot,
  MarketDetail,
  MarketSummary,
} from "../../domain/market";
import { marketDetailSchema, marketSummarySchema } from "../../domain/market";
import type {
  Trade,
  TradeDraft,
  TradeFilters,
} from "../../domain/trade";
import {
  tradeDraftSchema,
  tradeFiltersSchema,
  tradeSchema,
} from "../../domain/trade";
import {
  createWirePageSchema,
  HttpTransport,
  type HttpTransportOptions,
} from "./http-transport";
import {
  subscribeToReportStream,
  type ReportEventSourceFactory,
} from "./report-stream";
import type { ReportRunCreated, WorkbenchApi } from "./workbench-api";
import type { MarketDataSource } from "../config/env";
import { z } from "zod";

export class WorkbenchEndpointUnavailableError extends Error {
  readonly operation: keyof WorkbenchApi;

  constructor(operation: keyof WorkbenchApi) {
    super(
      `HTTP endpoint for ${operation} is unavailable until its backend route is defined`,
    );
    this.name = "WorkbenchEndpointUnavailableError";
    this.operation = operation;
  }
}

export interface HttpWorkbenchApiOptions extends HttpTransportOptions {
  marketDataSource?: MarketDataSource;
  eventSourceFactory?: ReportEventSourceFactory;
}

const marketInputSchema = z.object({
  symbol: z.enum(["BTCUSDT", "ETHUSDT"]),
  timeframes: z.array(z.enum(["15m", "1h", "4h", "1d"])).min(1),
});
const marketSummaryListSchema = z.object({
  items: z.array(marketSummarySchema),
});
const reportStartSchema = z.object({ symbol: z.enum(["BTCUSDT", "ETHUSDT"]) });
const analysisRunResultSchema = z.object({
  analysisId: identifierSchema,
  reportId: identifierSchema,
});
const analysisReportPageSchema = createWirePageSchema(
  analysisReportSummarySchema,
);
const tradeWireSchema = z
  .object({
    id: identifierSchema,
    symbol: z.enum(["BTCUSDT", "ETHUSDT"]),
    direction: z.enum(["long", "short"]),
    horizon: z.enum(["short_term", "medium_term"]),
    labels: z.array(z.string()),
    linkedReportId: identifierSchema.nullable(),
    leverage: z.string(),
    legs: z.array(
      z.object({
        id: identifierSchema,
        action: z.enum(["open", "reduce", "close"]),
        executedAt: z.string(),
        price: z.string(),
        quantity: z.string(),
        fee: z.string(),
      }),
    ),
    cashflows: z.array(
      z.object({
        id: identifierSchema,
        occurredAt: z.string(),
        amount: z.string(),
        reason: z.string(),
      }),
    ),
    thesis: z.string(),
    review: z.string(),
    status: z.enum(["open", "closed"]),
    netPnl: z.string(),
    openedAt: z.string(),
    closedAt: z.string().nullable(),
    createdAt: z.string(),
    updatedAt: z.string(),
  })
  .transform((wire): Trade =>
    tradeSchema.parse({
      ...wire,
      fundingCashflows: wire.cashflows,
    }),
  );
const tradePageSchema = createWirePageSchema(tradeWireSchema);

function unavailable<T>(operation: keyof WorkbenchApi): Promise<T> {
  return Promise.reject(new WorkbenchEndpointUnavailableError(operation));
}

export class HttpWorkbenchApi implements WorkbenchApi {
  private readonly transport: HttpTransport;
  private readonly marketApiPrefix: string;
  private readonly eventSourceFactory: ReportEventSourceFactory | undefined;

  constructor(options: HttpWorkbenchApiOptions) {
    const {
      marketDataSource = "live",
      eventSourceFactory,
      ...transportOptions
    } = options;
    this.transport = new HttpTransport(transportOptions);
    this.marketApiPrefix =
      marketDataSource === "research" ? "/api/v1/research" : "/api/v1";
    this.eventSourceFactory = eventSourceFactory;
  }

  async listMarketSummaries(): Promise<MarketSummary[]> {
    return (
      await this.transport.request(
        `${this.marketApiPrefix}/markets?symbols=BTCUSDT&symbols=ETHUSDT`,
        marketSummaryListSchema,
      )
    ).items;
  }

  getDashboard(): Promise<DashboardSnapshot> {
    return unavailable("getDashboard");
  }

  getMarket(input: {
    symbol: Symbol;
    timeframes: Timeframe[];
  }): Promise<MarketDetail> {
    const parsedInput = marketInputSchema.parse(input);
    const query = new URLSearchParams();
    for (const timeframe of parsedInput.timeframes) {
      query.append("timeframes", timeframe);
    }
    return this.transport.request(
      `${this.marketApiPrefix}/market/${parsedInput.symbol}?${query.toString()}`,
      marketDetailSchema,
    );
  }

  async listReports(
    filters: ReportFilters,
  ): Promise<Page<AnalysisReportSummary>> {
    const parsedFilters = reportFiltersSchema.parse(filters);
    const query = new URLSearchParams({
      page: String(parsedFilters.page),
      page_size: String(parsedFilters.pageSize),
    });
    if (parsedFilters.symbol !== undefined) {
      query.set("symbol", parsedFilters.symbol);
    }
    if (parsedFilters.status !== undefined) {
      query.set("status", parsedFilters.status);
    }
    return this.transport.request(
      `/api/v1/analysis-runs?${query.toString()}`,
      analysisReportPageSchema,
    );
  }

  getReport(reportId: string): Promise<AnalysisReport> {
    const parsedReportId = identifierSchema.parse(reportId);
    return this.transport.request(
      `/api/v1/analysis-runs/${encodeURIComponent(parsedReportId)}`,
      analysisReportSchema,
    );
  }

  async startReport(input: {
    symbol: Symbol;
  }): Promise<ReportRunCreated> {
    const parsedInput = reportStartSchema.parse(input);
    const result = await this.transport.request(
      "/api/v1/analysis-runs",
      analysisRunResultSchema,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsedInput),
      },
    );
    return result;
  }

  async retryReport(reportId: string): Promise<ReportRunCreated> {
    const parsedReportId = identifierSchema.parse(reportId);
    const result = await this.transport.request(
      `/api/v1/analysis-runs/${encodeURIComponent(parsedReportId)}/retry`,
      analysisRunResultSchema,
      { method: "POST" },
    );
    return result;
  }

  subscribeReport(
    analysisId: string,
    onEvent: (event: AnalysisStreamEvent) => void,
  ): () => void {
    const parsedAnalysisId = identifierSchema.parse(analysisId);
    const options = {
      url: this.transport.absoluteUrl(
        `/api/v1/analysis-runs/${encodeURIComponent(parsedAnalysisId)}/events`,
      ),
      onEvent,
    };
    return this.eventSourceFactory === undefined
      ? subscribeToReportStream(options)
      : subscribeToReportStream({
          ...options,
          eventSourceFactory: this.eventSourceFactory,
        });
  }

  listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    const parsedFilters = tradeFiltersSchema.parse(filters);
    const query = new URLSearchParams({
      page: String(parsedFilters.page),
      page_size: String(parsedFilters.pageSize),
    });
    if (parsedFilters.symbol !== undefined) {
      query.set("symbol", parsedFilters.symbol);
    }
    if (parsedFilters.direction !== undefined) {
      query.set("direction", parsedFilters.direction);
    }
    if (parsedFilters.horizon !== undefined) {
      query.set("horizon", parsedFilters.horizon);
    }
    if (parsedFilters.status !== undefined) {
      query.set("status", parsedFilters.status);
    }
    if (parsedFilters.label !== undefined) {
      query.set("label", parsedFilters.label);
    }
    if (parsedFilters.from !== undefined) {
      query.set("from", parsedFilters.from);
    }
    if (parsedFilters.to !== undefined) {
      query.set("to", parsedFilters.to);
    }
    return this.transport.request(`/api/v1/trades?${query.toString()}`, tradePageSchema);
  }

  createTrade(draft: TradeDraft): Promise<Trade> {
    return this.saveTrade("/api/v1/trades", "POST", draft);
  }

  updateTrade(tradeId: string, draft: TradeDraft): Promise<Trade> {
    const parsedTradeId = identifierSchema.parse(tradeId);
    return this.saveTrade(
      `/api/v1/trades/${encodeURIComponent(parsedTradeId)}`,
      "PUT",
      draft,
    );
  }

  getAnalytics(filters: AnalyticsFilters): Promise<AnalyticsSnapshot> {
    const parsedFilters = analyticsFiltersSchema.parse(filters);
    const query = new URLSearchParams();
    if (parsedFilters.symbol !== undefined) {
      query.set("symbol", parsedFilters.symbol);
    }
    if (parsedFilters.direction !== undefined) {
      query.set("direction", parsedFilters.direction);
    }
    if (parsedFilters.horizon !== undefined) {
      query.set("horizon", parsedFilters.horizon);
    }
    if (parsedFilters.label !== undefined) {
      query.set("label", parsedFilters.label);
    }
    if (parsedFilters.from !== undefined) {
      query.set("from", parsedFilters.from);
    }
    if (parsedFilters.to !== undefined) {
      query.set("to", parsedFilters.to);
    }
    const suffix = query.size === 0 ? "" : `?${query.toString()}`;
    return this.transport.request(`/api/v1/analytics${suffix}`, analyticsSnapshotSchema);
  }

  private saveTrade(
    path: string,
    method: "POST" | "PUT",
    draft: TradeDraft,
  ): Promise<Trade> {
    const parsedDraft = tradeDraftSchema.parse(draft);
    const { fundingCashflows, ...requestDraft } = parsedDraft;
    return this.transport.request(path, tradeWireSchema, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...requestDraft,
        cashflows: fundingCashflows,
      }),
    });
  }
}
