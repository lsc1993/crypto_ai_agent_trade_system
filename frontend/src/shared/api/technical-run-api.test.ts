import { describe, expect, it } from "vitest";
import { HttpWorkbenchApi } from "./http-workbench-api";

import { queuedRun } from "../../test/technical-run-fixture";

describe("background technical research API", () => {
  it("uses validated task endpoints with an idempotency key", async () => {
    const calls: string[] = [];
    const api = new HttpWorkbenchApi({ baseUrl: "http://localhost:8000", fetchImpl: (url) => {
      calls.push(url instanceof Request ? url.url : url.toString()); return Promise.resolve(new Response(JSON.stringify(queuedRun), {status: 202}));
    }});
    const run = await api.startTechnicalReportRun({symbol: "BTCUSDT", requestId: queuedRun.id});
    expect(run.status).toBe("queued");
    await expect(api.getTechnicalReportRun(run.id)).resolves.toEqual(queuedRun);
    expect(calls[0]).toContain("/technical-reports/runs");
    expect(calls[1]).toContain(`/runs/${run.id}`);
  });
});
