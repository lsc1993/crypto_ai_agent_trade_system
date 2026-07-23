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
  symbolSchema,
  timeframeSchema,
  type Page,
  type Symbol,
  type Timeframe,
} from "../../domain/primitives";
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
  tradeDraftSchema,
  tradeFiltersSchema,
  tradeSchema,
  type Trade,
  type TradeDraft,
  type TradeFilters,
} from "../../domain/trade";
import {
  subscribeToReportStream,
  type ReportEventSourceFactory,
} from "./report-stream";
import type { WorkbenchApi } from "./workbench-api";

const errorEnvelopeSchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.unknown().optional(),
});
const analysisResultSchema = z.object({ analysisId: identifierSchema });
const marketInputSchema = z.object({
  symbol: symbolSchema,
  timeframes: z.array(timeframeSchema).min(1),
});

function wirePageSchema<T>(itemSchema: z.ZodType<T>) {
  return z
    .object({
      items: z.array(itemSchema),
      page: z.number().int().positive(),
      page_size: z.number().int().positive(),
      total: z.number().int().nonnegative(),
    })
    .transform(
      (wire): Page<T> => ({
        items: wire.items,
        page: wire.page,
        pageSize: wire.page_size,
        total: wire.total,
      }),
    );
}

export class WorkbenchHttpError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "WorkbenchHttpError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export class WorkbenchResponseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WorkbenchResponseError";
  }
}

export interface HttpWorkbenchApiOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  eventSourceFactory?: ReportEventSourceFactory;
}

function addOptionalQuery(
  search: URLSearchParams,
  name: string,
  value: string | undefined,
): void {
  if (value !== undefined) {
    search.set(name, value);
  }
}

export class HttpWorkbenchApi implements WorkbenchApi {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly eventSourceFactory: ReportEventSourceFactory | undefined;

  constructor(options: HttpWorkbenchApiOptions) {
    const parsedUrl = z
      .url()
      .refine((value) => {
        const protocol = new URL(value).protocol;
        return protocol === "http:" || protocol === "https:";
      })
      .parse(options.baseUrl);
    this.baseUrl = parsedUrl;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch;
    this.eventSourceFactory = options.eventSourceFactory;
  }

  private async request<T>(
    path: string,
    schema: z.ZodType<T>,
    init: RequestInit = {},
  ): Promise<T> {
    const response = await this.fetchImpl(new URL(path, this.baseUrl), {
      ...init,
      headers: {
        Accept: "application/json",
        ...init.headers,
      },
    });
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new WorkbenchResponseError(
        `HTTP response from ${path} was not valid JSON`,
      );
    }

    if (!response.ok) {
      const envelope = errorEnvelopeSchema.safeParse(body);
      if (!envelope.success) {
        throw new WorkbenchResponseError(
          `HTTP error response from ${path} did not match the error envelope`,
        );
      }
      throw new WorkbenchHttpError(
        response.status,
        envelope.data.code,
        envelope.data.message,
        envelope.data.details,
      );
    }

    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      throw new WorkbenchResponseError(
        `HTTP response from ${path} did not match the workbench contract`,
      );
    }
    return parsed.data;
  }

  getDashboard(signal?: AbortSignal): Promise<DashboardSnapshot> {
    return this.request("/api/v1/dashboard", dashboardSnapshotSchema, {
      signal: signal ?? null,
    });
  }

  getMarket(
    input: { symbol: Symbol; timeframes: Timeframe[] },
    signal?: AbortSignal,
  ): Promise<MarketDetail> {
    const parsed = marketInputSchema.parse(input);
    const search = new URLSearchParams();
    for (const timeframe of parsed.timeframes) {
      search.append("timeframe", timeframe);
    }
    return this.request(
      `/api/v1/markets/${parsed.symbol}?${search.toString()}`,
      marketDetailSchema,
      { signal: signal ?? null },
    );
  }

  listReports(
    filters: ReportFilters,
    signal?: AbortSignal,
  ): Promise<Page<AnalysisReportSummary>> {
    const parsed = reportFiltersSchema.parse(filters);
    const search = new URLSearchParams({
      page: String(parsed.page),
      page_size: String(parsed.pageSize),
    });
    addOptionalQuery(search, "symbol", parsed.symbol);
    addOptionalQuery(search, "status", parsed.status);
    return this.request(
      `/api/v1/reports?${search.toString()}`,
      wirePageSchema(analysisReportSummarySchema),
      { signal: signal ?? null },
    );
  }

  getReport(
    reportId: string,
    signal?: AbortSignal,
  ): Promise<AnalysisReport> {
    const parsedId = identifierSchema.parse(reportId);
    return this.request(
      `/api/v1/reports/${encodeURIComponent(parsedId)}`,
      analysisReportSchema,
      { signal: signal ?? null },
    );
  }

  startReport(
    input: { symbol: Symbol },
    signal?: AbortSignal,
  ): Promise<{ analysisId: string }> {
    const body = z.object({ symbol: symbolSchema }).parse(input);
    return this.request("/api/v1/reports", analysisResultSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: signal ?? null,
    });
  }

  retryReport(
    reportId: string,
    signal?: AbortSignal,
  ): Promise<{ analysisId: string }> {
    const parsedId = identifierSchema.parse(reportId);
    return this.request(
      `/api/v1/reports/${encodeURIComponent(parsedId)}/retry`,
      analysisResultSchema,
      { method: "POST", signal: signal ?? null },
    );
  }

  subscribeReport(
    analysisId: string,
    onEvent: (event: AnalysisStreamEvent) => void,
  ): () => void {
    if (this.eventSourceFactory === undefined) {
      return subscribeToReportStream({
        baseUrl: this.baseUrl,
        analysisId,
        onEvent,
      });
    }
    return subscribeToReportStream({
      baseUrl: this.baseUrl,
      analysisId,
      onEvent,
      eventSourceFactory: this.eventSourceFactory,
    });
  }

  listTrades(
    filters: TradeFilters,
    signal?: AbortSignal,
  ): Promise<Page<Trade>> {
    const parsed = tradeFiltersSchema.parse(filters);
    const search = new URLSearchParams({
      page: String(parsed.page),
      page_size: String(parsed.pageSize),
    });
    addOptionalQuery(search, "symbol", parsed.symbol);
    addOptionalQuery(search, "direction", parsed.direction);
    addOptionalQuery(search, "horizon", parsed.horizon);
    addOptionalQuery(search, "status", parsed.status);
    addOptionalQuery(search, "label", parsed.label);
    addOptionalQuery(search, "from", parsed.from);
    addOptionalQuery(search, "to", parsed.to);
    return this.request(
      `/api/v1/trades?${search.toString()}`,
      wirePageSchema(tradeSchema),
      { signal: signal ?? null },
    );
  }

  createTrade(
    draft: TradeDraft,
    signal?: AbortSignal,
  ): Promise<Trade> {
    const body = tradeDraftSchema.parse(draft);
    return this.request("/api/v1/trades", tradeSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: signal ?? null,
    });
  }

  updateTrade(
    tradeId: string,
    draft: TradeDraft,
    signal?: AbortSignal,
  ): Promise<Trade> {
    const parsedId = identifierSchema.parse(tradeId);
    const body = tradeDraftSchema.parse(draft);
    return this.request(
      `/api/v1/trades/${encodeURIComponent(parsedId)}`,
      tradeSchema,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: signal ?? null,
      },
    );
  }

  getAnalytics(
    filters: AnalyticsFilters,
    signal?: AbortSignal,
  ): Promise<AnalyticsSnapshot> {
    const parsed = analyticsFiltersSchema.parse(filters);
    const search = new URLSearchParams();
    addOptionalQuery(search, "symbol", parsed.symbol);
    addOptionalQuery(search, "direction", parsed.direction);
    addOptionalQuery(search, "horizon", parsed.horizon);
    addOptionalQuery(search, "label", parsed.label);
    addOptionalQuery(search, "from", parsed.from);
    addOptionalQuery(search, "to", parsed.to);
    const query = search.size > 0 ? `?${search.toString()}` : "";
    return this.request(
      `/api/v1/analytics${query}`,
      analyticsSnapshotSchema,
      { signal: signal ?? null },
    );
  }
}
