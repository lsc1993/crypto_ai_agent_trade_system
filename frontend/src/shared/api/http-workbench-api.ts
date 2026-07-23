import type {
  AnalyticsFilters,
  AnalyticsSnapshot,
} from "../../domain/analytics";
import type {
  DashboardSnapshot,
  MarketDetail,
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
import {
  HttpTransport,
  type HttpTransportOptions,
} from "./http-transport";
import type { WorkbenchApi } from "./workbench-api";

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

export type HttpWorkbenchApiOptions = HttpTransportOptions;

function unavailable<T>(operation: keyof WorkbenchApi): Promise<T> {
  return Promise.reject(new WorkbenchEndpointUnavailableError(operation));
}

export class HttpWorkbenchApi implements WorkbenchApi {
  constructor(options: HttpWorkbenchApiOptions) {
    if (options.fetchImpl === undefined) {
      new HttpTransport({ baseUrl: options.baseUrl });
    } else {
      new HttpTransport({
        baseUrl: options.baseUrl,
        fetchImpl: options.fetchImpl,
      });
    }
  }

  getDashboard(): Promise<DashboardSnapshot> {
    return unavailable("getDashboard");
  }

  getMarket(input: {
    symbol: Symbol;
    timeframes: Timeframe[];
  }): Promise<MarketDetail> {
    void input;
    return unavailable("getMarket");
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
