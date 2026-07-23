import { describe, expect, it, vi } from "vitest";

import { parseTradeDraft } from "../../domain/trade";
import { MockWorkbenchApi } from "../api/mock-workbench-api";
import { mockTradeDraft } from "./fixtures";
import { resetMockWorkbench } from "./reset";

describe("MockWorkbenchApi", () => {
  it("returns deterministic fixtures dated in the past", async () => {
    const api = new MockWorkbenchApi();

    const first = await api.getDashboard();
    const second = await api.getDashboard();

    expect(second).toEqual(first);
    expect(Date.parse(first.generatedAt)).toBeLessThan(
      Date.parse("2026-01-01T00:00:00Z"),
    );
  });

  it("rejects non-canonical decimals and non-UTC timestamps", () => {
    expect(() =>
      parseTradeDraft({
        ...mockTradeDraft,
        leverage: "1e1",
      }),
    ).toThrow();
    expect(() =>
      parseTradeDraft({
        ...mockTradeDraft,
        legs: [
          {
            ...mockTradeDraft.legs[0],
            executedAt: "2025-01-01T08:00:00+08:00",
          },
        ],
      }),
    ).toThrow();
  });

  it("validates trade-leg reduction semantics", () => {
    expect(() =>
      parseTradeDraft({
        ...mockTradeDraft,
        legs: [
          {
            id: "leg-open",
            action: "open",
            executedAt: "2025-01-01T00:00:00Z",
            price: "100",
            quantity: "1",
            fee: "0",
          },
          {
            id: "leg-reduce",
            action: "reduce",
            executedAt: "2025-01-01T01:00:00Z",
            price: "105",
            quantity: "1",
            fee: "0",
          },
        ],
      }),
    ).toThrow(/reduce/i);
  });

  it("ignores invalid localStorage state and reset restores the seed", async () => {
    localStorage.setItem("crypto-workbench:mock-state:v1", "{not-json");
    const api = new MockWorkbenchApi();

    const before = await api.listTrades({ page: 1, pageSize: 20 });
    await api.createTrade(mockTradeDraft);
    const changed = await api.listTrades({ page: 1, pageSize: 20 });
    resetMockWorkbench();
    const restored = await new MockWorkbenchApi().listTrades({
      page: 1,
      pageSize: 20,
    });

    expect(changed.total).toBe(before.total + 1);
    expect(restored).toEqual(before);
  });

  it("emits queued, running, and completed report lifecycle events", () => {
    vi.useFakeTimers();
    const api = new MockWorkbenchApi();
    const statuses: string[] = [];

    const unsubscribe = api.subscribeReport("analysis-test", (event) => {
      statuses.push(event.status);
    });
    vi.runAllTimers();

    expect(statuses).toEqual(["queued", "running", "completed"]);
    unsubscribe();
  });

  it("creates a new analysis ID every time a report is retried", async () => {
    const api = new MockWorkbenchApi();

    const first = await api.retryReport("report-btc-001");
    const second = await api.retryReport("report-btc-001");

    expect(first.analysisId).not.toBe(second.analysisId);
    expect(first.analysisId).toMatch(/^analysis-retry-/);
  });
});
