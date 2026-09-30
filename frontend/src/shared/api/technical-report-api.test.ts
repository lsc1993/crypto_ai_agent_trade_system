import { describe, expect, it, vi } from "vitest";

import { technicalReportWire } from "../../test/technical-report-fixture";
import { HttpWorkbenchApi } from "./http-workbench-api";
import { HybridWorkbenchApi } from "./hybrid-workbench-api";
import { MockWorkbenchApi } from "./mock-workbench-api";
import { WorkbenchResponseError } from "./http-transport";

describe("technical report adapters", () => {
  it("posts and reads a complete report on the independent route", async () => {
    const fetchImpl: typeof fetch = vi.fn(() => Promise.resolve(Response.json(technicalReportWire)));
    const api = new HttpWorkbenchApi({ baseUrl: "http://localhost:8000", fetchImpl });
    await expect(api.startTechnicalReport({ symbol: "BTCUSDT" })).resolves.toMatchObject({ id: technicalReportWire.id });
    await expect(api.getTechnicalReport(technicalReportWire.id)).resolves.toMatchObject({ analysisId: technicalReportWire.analysisId });
    const calls = vi.mocked(fetchImpl).mock.calls;
    expect(new URL(calls[0]?.[0] as URL).pathname).toBe("/api/v1/technical-reports");
    expect((calls[0]?.[1] as RequestInit).body).toBe('{"symbol":"BTCUSDT"}');
    expect(new URL(calls[1]?.[0] as URL).pathname).toBe(`/api/v1/technical-reports/${technicalReportWire.id}`);
  });

  it("uses camelCase pagination and rejects malformed financial values", async () => {
    const fetchImpl: typeof fetch = vi.fn(() => Promise.resolve(Response.json({ items: [technicalReportWire], page: 2, pageSize: 5, total: 6 })));
    const api = new HttpWorkbenchApi({ baseUrl: "http://localhost:8000", fetchImpl });
    await expect(api.listTechnicalReports({ symbol: "BTCUSDT", page: 2, pageSize: 5 })).resolves.toMatchObject({ total: 6 });
    const url = new URL(vi.mocked(fetchImpl).mock.calls[0]?.[0] as URL);
    expect(url.searchParams.get("pageSize")).toBe("5");
    expect(url.searchParams.get("page_size")).toBeNull();
    expect(url.searchParams.get("symbol")).toBe("BTCUSDT");
    const malformed: typeof fetch = vi.fn(() => Promise.resolve(Response.json({ ...technicalReportWire, analysis: { ...technicalReportWire.analysis, facts: { ...technicalReportWire.analysis.facts, rangeHigh: 70000 } } })));
    await expect(new HttpWorkbenchApi({ baseUrl: "http://localhost:8000", fetchImpl: malformed }).getTechnicalReport(technicalReportWire.id)).rejects.toBeInstanceOf(WorkbenchResponseError);
  });

  it("delegates all technical operations through Hybrid without Mock fallback", async () => {
    const remote = new HttpWorkbenchApi({ baseUrl: "http://localhost:8000", fetchImpl: vi.fn(() => Promise.resolve(Response.json(technicalReportWire))) });
    const api = new HybridWorkbenchApi(new MockWorkbenchApi(), remote);
    await expect(api.startTechnicalReport({ symbol: "BTCUSDT" })).resolves.toMatchObject({ id: technicalReportWire.id, status: "completed" });
    await expect(api.getTechnicalReport(technicalReportWire.id)).resolves.toMatchObject({ id: technicalReportWire.id });
  });

  it("keeps Mock creation visibly demonstrative and never returns fabricated AI narrative", async () => {
    const api = new MockWorkbenchApi();
    const report = await api.startTechnicalReport({ symbol: "BTCUSDT" });
    expect(report.status).toBe("degraded");
    expect(report.narrative).toBeNull();
    expect(report.analysis.quality.reasons).toContain("mock_demo_only");
    await expect(api.listTechnicalReports({ symbol: "BTCUSDT", page: 1, pageSize: 20 })).resolves.toMatchObject({ total: 1 });
  });
});
