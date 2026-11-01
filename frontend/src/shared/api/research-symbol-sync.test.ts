import { describe, expect, it, vi } from "vitest";

import { HttpWorkbenchApi } from "./http-workbench-api";
import { HybridWorkbenchApi } from "./hybrid-workbench-api";
import { WorkbenchHttpError, WorkbenchResponseError } from "./http-transport";
import { MockWorkbenchApi } from "./mock-workbench-api";

const failedId = "00000000-0000-4000-8000-000000000001";
const queuedRun = {
  id: "00000000-0000-4000-8000-000000000002",
  symbol: "SOLUSDT", version: 2, status: "queued", stage: "queued",
  createdAt: "2026-11-01T00:00:00Z", startedAt: null, completedAt: null,
  leaseToken: null, leaseUntil: null, snapshotId: null, sources: [], error: null,
};

describe("research symbol sync retry adapters", () => {
  it("posts the failed run UUID and validates the complete camelCase run response", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(Response.json(queuedRun, { status: 202 }));
    const api = new HttpWorkbenchApi({ baseUrl: "http://localhost:8000", fetchImpl });
    await expect(api.retryResearchSymbolSync("SOLUSDT", failedId)).resolves.toEqual(queuedRun);
    const [url, init] = fetchImpl.mock.calls[0]!;
    if (!(url instanceof URL) || typeof init?.body !== "string") {
      throw new Error("Expected a URL and JSON request body");
    }
    expect(url.pathname).toBe("/api/v1/research-symbols/SOLUSDT/sync/retry");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ runId: failedId });
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
  });

  it("rejects invalid IDs before sending and rejects incomplete run responses", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ id: failedId, status: "queued" }));
    const api = new HttpWorkbenchApi({ baseUrl: "http://localhost:8000", fetchImpl });
    expect(() => api.retryResearchSymbolSync("SOLUSDT", "invalid")).toThrow();
    expect(fetchImpl).not.toHaveBeenCalled();
    await expect(api.retryResearchSymbolSync("SOLUSDT", failedId)).rejects.toBeInstanceOf(WorkbenchResponseError);
  });

  it("propagates Hybrid remote conflicts without changing the offline directory", async () => {
    const mock = new MockWorkbenchApi();
    const before = await mock.listResearchSymbols();
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(Response.json({
      code: "sync_retry_conflict", message: "任务状态已变化，请刷新后重试。", details: {},
    }, { status: 409 }));
    const api = new HybridWorkbenchApi(mock, new HttpWorkbenchApi({ baseUrl: "http://localhost:8000", fetchImpl }));
    await expect(api.retryResearchSymbolSync("BTCUSDT", failedId)).rejects.toBeInstanceOf(WorkbenchHttpError);
    expect(await mock.listResearchSymbols()).toEqual(before);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("keeps Mock retry explicitly offline and never simulates a public sync", async () => {
    const mock = new MockWorkbenchApi();
    const before = await mock.listResearchSymbols();
    await expect(mock.retryResearchSymbolSync("BTCUSDT", failedId)).rejects.toThrow(/离线/);
    expect(await mock.listResearchSymbols()).toEqual(before);
  });
});
