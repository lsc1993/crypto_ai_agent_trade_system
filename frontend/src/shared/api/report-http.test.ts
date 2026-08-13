import { describe, expect, it, vi } from "vitest";

import { HttpWorkbenchApi } from "./http-workbench-api";
import { WorkbenchResponseError } from "./http-transport";
import type { ReportEventSource } from "./report-stream";

const reportWire = {
  id: "00000000-0000-4000-8000-000000000601",
  analysisId: "00000000-0000-4000-8000-000000000602",
  symbol: "BTCUSDT",
  status: "completed",
  title: "BTCUSDT public market research",
  summary: "Frozen public evidence research.",
  createdAt: "2026-08-10T12:00:00Z",
  dataCutoffAt: "2026-08-10T12:00:00Z",
  generatorKind: "langgraph_deepseek",
  facts: [],
  inferences: [],
  risks: [],
  limitations: ["Not trading advice."],
  evidence: [
    {
      id: "00000000-0000-4000-8000-000000000603",
      symbol: "BTCUSDT",
      source: "CoinDesk",
      sourceUrl: "https://www.coindesk.com/example",
      observedAt: "2026-08-10T12:00:00Z",
      summary: "Public English evidence.",
    },
  ],
  agentAnalysis: {
    horizon: "1_to_3_days",
    outlook: "neutral",
    confidence: "medium",
    trendAlignment: { "1h": "neutral" },
    supportZones: [
      {
        lower: "67000.10",
        upper: "67100.20",
        timeframe: "1h",
        rationale: "Closed-candle support.",
      },
    ],
    resistanceZones: [],
    catalysts: [
      {
        category: "market",
        direction: "neutral",
        claim: "Public evidence is mixed.",
        evidenceIds: ["00000000-0000-4000-8000-000000000603"],
        timing: "Within one to three days.",
      },
    ],
    risksAndInvalidation: [],
    dataQuality: {
      freshness: "fresh",
      missingInputs: [],
      sourceCoverage: "partial",
    },
    limitations: ["Not trading advice."],
  },
} as const;

describe("HttpWorkbenchApi agent reports", () => {
  it("posts only the selected symbol and reads the validated agent report", async () => {
    const fetchImpl: typeof fetch = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({
          analysisId: reportWire.analysisId,
          reportId: reportWire.id,
        }),
      )
      .mockResolvedValueOnce(Response.json(reportWire));
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(api.startReport({ symbol: "BTCUSDT" })).resolves.toEqual({
      analysisId: reportWire.analysisId,
      reportId: reportWire.id,
    });
    await expect(api.getReport(reportWire.id)).resolves.toMatchObject({
      generatorKind: "langgraph_deepseek",
      agentAnalysis: {
        horizon: "1_to_3_days",
        supportZones: [{ lower: "67000.10" }],
      },
    });

    const calls = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls;
    expect(new URL(calls[0]?.[0] as URL).pathname).toBe("/api/v1/analysis-runs");
    const request = calls[0]?.[1] as RequestInit;
    expect(request.method).toBe("POST");
    expect(request.body).toBe(JSON.stringify({ symbol: "BTCUSDT" }));
    expect(new URL(calls[1]?.[0] as URL).pathname).toBe(
      `/api/v1/analysis-runs/${reportWire.id}`,
    );
  });

  it("rejects Agent citations outside the current report evidence", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(
        Response.json({
          ...reportWire,
          agentAnalysis: {
            ...reportWire.agentAnalysis,
            catalysts: [
              {
                ...reportWire.agentAnalysis.catalysts[0],
                evidenceIds: ["00000000-0000-4000-8000-000000000604"],
              },
            ],
          },
        }),
      ),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(api.getReport(reportWire.id)).rejects.toBeInstanceOf(
      WorkbenchResponseError,
    );
  });
});

const deterministicReportSummary = {
  id: "report-btc-001",
  analysisId: "analysis-btc-001",
  symbol: "BTCUSDT",
  status: "degraded",
  title: "BTCUSDT 持久化市场研究已降级",
  summary: "当前证据不足，无法形成市场研究结论。",
  createdAt: "2026-07-30T12:00:00Z",
  dataCutoffAt: null,
  generatorKind: "deterministic",
} as const;

const deterministicReportDetail = {
  ...deterministicReportSummary,
  facts: [],
  inferences: [],
  risks: ["持久化市场研究数据不可用"],
  limitations: ["报告未形成市场结论，需等待新的持久化市场数据。"],
  evidence: [],
  agentAnalysis: null,
} as const;

class FakeReportEventSource implements ReportEventSource {
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closeCount = 0;

  close(): void {
    this.closeCount += 1;
  }
}

describe("HttpWorkbenchApi existing report HTTP mapping", () => {
  it("uses analysis-run paths and maps deterministic report pages", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(
        Response.json({
          items: [deterministicReportSummary],
          page: 2,
          page_size: 10,
          total: 1,
        }),
      ),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(
      api.listReports({
        page: 2,
        pageSize: 10,
        symbol: "BTCUSDT",
        status: "degraded",
      }),
    ).resolves.toEqual({
      items: [deterministicReportSummary],
      page: 2,
      pageSize: 10,
      total: 1,
    });
    const requestUrl = new URL(
      (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as URL,
    );
    expect(requestUrl.pathname).toBe("/api/v1/analysis-runs");
    expect(requestUrl.searchParams.get("page")).toBe("2");
    expect(requestUrl.searchParams.get("page_size")).toBe("10");
    expect(requestUrl.searchParams.get("symbol")).toBe("BTCUSDT");
    expect(requestUrl.searchParams.get("status")).toBe("degraded");
  });

  it("reads one encoded deterministic report path", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(Response.json(deterministicReportDetail)),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(api.getReport("report/id?fragment")).resolves.toEqual(
      deterministicReportDetail,
    );
    const requestUrl = new URL(
      (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as URL,
    );
    expect(requestUrl.pathname).toBe(
      "/api/v1/analysis-runs/report%2Fid%3Ffragment",
    );
  });

  it("posts report creation and retry without leaking state into the URL", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(
        Response.json({
          analysisId: "analysis-created-001",
          reportId: "report-created-001",
        }),
      ),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(api.startReport({ symbol: "BTCUSDT" })).resolves.toEqual({
      analysisId: "analysis-created-001",
      reportId: "report-created-001",
    });
    await expect(api.retryReport("report/id?fragment")).resolves.toEqual({
      analysisId: "analysis-created-001",
      reportId: "report-created-001",
    });
    const calls = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls;
    expect(new URL(calls[0]?.[0] as URL).pathname).toBe("/api/v1/analysis-runs");
    expect(calls[0]?.[1]).toMatchObject({ method: "POST" });
    expect((calls[0]?.[1] as RequestInit).body).toBe(
      JSON.stringify({ symbol: "BTCUSDT" }),
    );
    expect(new URL(calls[1]?.[0] as URL).pathname).toBe(
      "/api/v1/analysis-runs/report%2Fid%3Ffragment/retry",
    );
    expect(calls[1]?.[1]).toMatchObject({ method: "POST" });
  });

  it("replays one valid report event and closes a malformed stream", () => {
    const eventSource = new FakeReportEventSource();
    const eventSourceFactory = vi.fn(() => eventSource);
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      eventSourceFactory,
    });
    const received: unknown[] = [];

    const unsubscribe = api.subscribeReport("analysis-btc-001", (event) => {
      received.push(event);
    });
    expect(eventSourceFactory).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/analysis-runs/analysis-btc-001/events",
    );
    eventSource.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({
          analysisId: "analysis-btc-001",
          symbol: "BTCUSDT",
          status: "degraded",
          occurredAt: "2026-07-30T12:00:00Z",
          message: "持久化市场研究报告已降级完成。",
        }),
      }),
    );
    expect(received).toHaveLength(1);

    eventSource.onmessage?.(new MessageEvent("message", { data: "not JSON" }));
    expect(eventSource.closeCount).toBe(1);
    unsubscribe();
    expect(eventSource.closeCount).toBe(2);
  });
});
