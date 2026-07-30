import { describe, expect, it, vi } from "vitest";

import { HttpWorkbenchApi } from "./http-workbench-api";
import type { ReportEventSource } from "./report-stream";

const reportSummary = {
  id: "report-btc-001",
  analysisId: "analysis-btc-001",
  symbol: "BTCUSDT",
  status: "degraded",
  title: "BTCUSDT 持久化市场研究已降级",
  summary: "当前证据不足，无法形成市场研究结论。",
  createdAt: "2026-07-30T12:00:00Z",
  dataCutoffAt: null,
};

const reportDetail = {
  ...reportSummary,
  facts: [],
  inferences: [],
  risks: ["持久化市场研究数据不可用"],
  limitations: ["报告未形成市场结论，需等待新的持久化市场数据。"],
  evidence: [],
};

class FakeReportEventSource implements ReportEventSource {
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closeCount = 0;

  close(): void {
    this.closeCount += 1;
  }
}

describe("HttpWorkbenchApi report HTTP mapping", () => {
  it("uses analysis-run paths and maps the report page wire contract", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(
        Response.json({
          items: [reportSummary],
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
      items: [reportSummary],
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

  it("reads a report detail through one encoded analysis-run path", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(Response.json(reportDetail)),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(api.getReport("report/id?fragment")).resolves.toEqual(
      reportDetail,
    );

    const requestUrl = new URL(
      (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as URL,
    );
    expect(requestUrl.pathname).toBe(
      "/api/v1/analysis-runs/report%2Fid%3Ffragment",
    );
  });

  it("posts report creation and retry requests without leaking state into the URL", async () => {
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
    });
    await expect(api.retryReport("report/id?fragment")).resolves.toEqual({
      analysisId: "analysis-created-001",
    });

    const start = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0];
    const retry = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[1];
    expect(start).toBeDefined();
    expect(retry).toBeDefined();
    if (start === undefined || retry === undefined) {
      throw new Error("Report requests were not sent");
    }
    expect(new URL(start[0] as URL).pathname).toBe("/api/v1/analysis-runs");
    expect(start[1]).toMatchObject({ method: "POST" });
    const startBody = (start[1] as RequestInit).body;
    if (typeof startBody !== "string") {
      throw new Error("Report creation request body must be JSON text");
    }
    expect(JSON.parse(startBody)).toEqual({
      symbol: "BTCUSDT",
    });
    expect(new URL(retry[0] as URL).pathname).toBe(
      "/api/v1/analysis-runs/report%2Fid%3Ffragment/retry",
    );
    expect(retry[1]).toMatchObject({ method: "POST" });
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
    expect(received).toEqual([
      {
        analysisId: "analysis-btc-001",
        symbol: "BTCUSDT",
        status: "degraded",
        occurredAt: "2026-07-30T12:00:00Z",
        message: "持久化市场研究报告已降级完成。",
      },
    ]);

    eventSource.onmessage?.(
      new MessageEvent("message", { data: "not JSON" }),
    );
    expect(eventSource.closeCount).toBe(1);

    unsubscribe();
    expect(eventSource.closeCount).toBe(2);
  });
});
