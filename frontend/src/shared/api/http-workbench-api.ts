import type {
  AnalyticsFilters,
  AnalyticsSnapshot,
} from "../../domain/analytics";
import type {
  DashboardSnapshot,
  MarketDetail,
  MarketSummary,
} from "../../domain/market";
import { marketDetailSchema, marketSummarySchema } from "../../domain/market";
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
import {
  HttpTransport,
  type HttpTransportOptions,
} from "./http-transport";
import type { WorkbenchApi } from "./workbench-api";
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
}

const marketInputSchema = z.object({
  symbol: z.enum(["BTCUSDT", "ETHUSDT"]),
  timeframes: z.array(z.enum(["15m", "1h", "4h", "1d"])).min(1),
});
const marketSummaryListSchema = z.object({
  items: z.array(marketSummarySchema),
});

function unavailable<T>(operation: keyof WorkbenchApi): Promise<T> {
  return Promise.reject(new WorkbenchEndpointUnavailableError(operation));
}

export class HttpWorkbenchApi implements WorkbenchApi {
  private readonly transport: HttpTransport;
  private readonly marketApiPrefix: string;

  constructor(options: HttpWorkbenchApiOptions) {
    const { marketDataSource = "live", ...transportOptions } = options;
    this.transport = new HttpTransport(transportOptions);
    this.marketApiPrefix =
      marketDataSource === "research" ? "/api/v1/research" : "/api/v1";
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

  listReports(
    filters: ReportFilters,
  ): Promise<Page<AnalysisReportSummary>> {
    void filters;
    return unavailable("listReports");
  }

  getReport(reportId: string): Promise<AnalysisReport> {
    void reportId;
    return unavailable("getReport");
  }

  startReport(input: {
    symbol: Symbol;
  }): Promise<{ analysisId: string }> {
    void input;
    return unavailable("startReport");
  }

  retryReport(reportId: string): Promise<{ analysisId: string }> {
    void reportId;
    return unavailable("retryReport");
  }

  subscribeReport(
    analysisId: string,
    onEvent: (event: AnalysisStreamEvent) => void,
  ): () => void {
    void analysisId;
    void onEvent;
    throw new WorkbenchEndpointUnavailableError("subscribeReport");
  }

  listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    void filters;
    return unavailable("listTrades");
  }

  createTrade(draft: TradeDraft): Promise<Trade> {
    void draft;
    return unavailable("createTrade");
  }

  updateTrade(tradeId: string, draft: TradeDraft): Promise<Trade> {
    void tradeId;
    void draft;
    return unavailable("updateTrade");
  }

  getAnalytics(filters: AnalyticsFilters): Promise<AnalyticsSnapshot> {
    void filters;
    return unavailable("getAnalytics");
  }
}
