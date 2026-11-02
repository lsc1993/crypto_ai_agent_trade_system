import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers";
import { researchSymbolEntrySchema, type ResearchSymbolEntry } from "../../domain/research-symbol";
import { MockWorkbenchApi } from "../../shared/api/mock-workbench-api";
import { WorkbenchHttpError } from "../../shared/api/http-transport";
import { ResearchSymbolManagementPage } from "./ResearchSymbolManagementPage";

const failedId = "00000000-0000-4000-8000-000000000001";
const queuedRun = {
  id: "00000000-0000-4000-8000-000000000002",
  symbol: "BTCUSDT", version: 1, status: "queued" as const, stage: "queued",
  createdAt: "2026-11-01T00:00:00Z", startedAt: null, completedAt: null,
  leaseToken: null, leaseUntil: null, snapshotId: null, sources: [], error: null,
};

async function directory(canResearch = false) {
  const api = new MockWorkbenchApi();
  const [original] = await api.listResearchSymbols();
  if (!original) throw new Error("Expected offline fixture");
  const entry: ResearchSymbolEntry = {
    ...original, canResearch, lastSync: { id: failedId, status: "failed", error: "private raw payload" },
  };
  const list = vi.spyOn(api, "listResearchSymbols").mockResolvedValue([entry]);
  return { api, entry, list };
}

function show(api: MockWorkbenchApi) {
  window.history.replaceState({}, "", "/research-symbols");
  return render(<AppProviders api={api}><ResearchSymbolManagementPage /></AppProviders>);
}

describe("research symbol sync recovery", () => {
  it.each([
    ["sync_timeout", "同步任务超时，请稍后重试。"],
    ["sync_interrupted", "同步任务已中断，请重试。"],
    ["sync_lease_expired", "同步任务租约已过期，请重试。"],
    ["market_sync_failed", "公开行情同步失败，请稍后重试。"],
    ["research_symbol_archived", "研究币对已归档，无法继续同步。"],
    ["private diagnostic body", "同步出现未知故障，请稍后重试。"],
  ])("shows a safe failure explanation for %s", async (error, message) => {
    const { api, entry, list } = await directory(true);
    list.mockResolvedValue([researchSymbolEntrySchema.parse({
      ...entry, lastSync: { id: failedId, status: "failed", error, stage: "private stage body" },
    })]);
    show(api);
    const card = await screen.findByRole("article", { name: "BTCUSDT" });
    expect(within(card).getByText(`失败原因：${message}`)).toBeVisible();
    expect(within(card).getByText("可研究")).toBeVisible();
    expect(card).not.toHaveTextContent(/private|sync_timeout|sync_interrupted|sync_lease_expired|market_sync_failed|research_symbol_archived/);
  });

  it("shows recorded lifecycle times and partial source coverage without displaying source bodies", async () => {
    const { api, entry, list } = await directory(true);
    list.mockResolvedValue([researchSymbolEntrySchema.parse({
      ...entry, lastSync: {
        ...queuedRun, status: "partial", stage: "private stage body",
        startedAt: "2026-11-01T00:00:01Z", completedAt: "2026-11-01T00:00:03Z",
        sources: [
          { name: "market", status: "available", message: "private market body", payload: { private: "source body" } },
          { name: "candles", status: "partial", message: "private candles body" },
          { name: "news", status: "missing" },
          { name: "etf", status: "unsupported" },
          { name: "funding", status: "failed" },
          { name: "derivatives", status: "available" },
          { name: "sentiment", status: "missing" },
        ],
      },
    })]);
    show(api);
    const card = await screen.findByRole("article", { name: "BTCUSDT" });
    for (const [label, value] of [
      ["创建时间（UTC）", "2026-11-01T00:00:00Z"],
      ["开始时间（UTC）", "2026-11-01T00:00:01Z"],
      ["结束时间（UTC）", "2026-11-01T00:00:03Z"],
    ] as const) {
      const time = within(card).getByText(value);
      expect(time).toHaveAttribute("datetime", value);
      expect(time.parentElement).toHaveTextContent(label);
    }
    for (const text of ["公开行情：可用", "K 线：部分覆盖", "新闻：缺失", "ETF：不支持", "资金费率：失败", "衍生品：可用", "情绪：缺失"]) {
      expect(within(card).getByText(text)).toBeVisible();
    }
    expect(within(card).getByText("最近同步：部分覆盖")).toBeVisible();
    expect(card).not.toHaveTextContent(/private|source body|就绪/);
  });

  it("keeps sparse offline diagnostics explicit without inventing lifecycle times", async () => {
    const api = new MockWorkbenchApi();
    show(api);
    const card = await screen.findByRole("article", { name: "BTCUSDT" });
    expect(within(card).getByText(/离线示例/)).toBeVisible();
    expect(within(card).getByText("同步时间未提供。")).toBeVisible();
    expect(within(card).getByText("来源覆盖未提供。")).toBeVisible();
    expect(card.querySelector("time")).toBeNull();
  });

  it("separates latest failure from retained research admission and hides raw sync errors", async () => {
    const { api } = await directory(true);
    show(api);
    const card = await screen.findByRole("article", { name: "BTCUSDT" });
    expect(within(card).getByText("可研究")).toBeVisible();
    expect(within(card).getByText("最近同步：失败")).toBeVisible();
    expect(within(card).getByRole("button", { name: "重试同步" })).toBeEnabled();
    expect(screen.queryByText(/private raw payload|同步中/)).not.toBeInTheDocument();
  });

  it("submits the failed ID once, disables while pending, and refreshes the queued state", async () => {
    const { api, entry, list } = await directory();
    let finish!: (value: typeof queuedRun) => void;
    const retry = vi.spyOn(api, "retryResearchSymbolSync").mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    show(api);
    const button = await screen.findByRole("button", { name: "重试同步" });
    await userEvent.click(button);
    expect(button).toBeDisabled();
    expect(retry).toHaveBeenCalledExactlyOnceWith("BTCUSDT", failedId);
    list.mockResolvedValue([{ ...entry, lastSync: queuedRun }]);
    act(() => finish(queuedRun));
    expect(await screen.findByText("最近同步：排队中")).toBeVisible();
    expect(screen.getByRole("button", { name: "重试同步" })).toBeDisabled();
  });

  it.each([
    [new Error("private transport payload"), "重试同步失败，请稍后重试。"],
    [new WorkbenchHttpError(409, "sync_retry_conflict", "任务状态已变化，请刷新后重试。", { raw: "private details" }), "任务状态已变化，请刷新后重试。"],
    [new WorkbenchHttpError(409, "sync_retry_conflict", "private message", {}), "任务状态已变化，请刷新后重试。"],
    [new WorkbenchHttpError(409, "research_symbol_sync_retry_conflict", "private message", {}), "任务状态已变化，请刷新后重试。"],
    [new WorkbenchHttpError(500, "unknown_error", "private message", {}), "重试同步失败，请稍后重试。"],
  ])("shows only a safe retry error", async (error, message) => {
    const { api } = await directory();
    vi.spyOn(api, "retryResearchSymbolSync").mockRejectedValue(error);
    show(api);
    await userEvent.click(await screen.findByRole("button", { name: "重试同步" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByText(/private/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试同步" })).toBeEnabled();
  });

  it("polls only queued/running entries every two seconds and stops at partial", async () => {
    const { api, entry, list } = await directory();
    list.mockResolvedValue([{ ...entry, lastSync: queuedRun }]);
    vi.useFakeTimers();
    await act(async () => { show(api); await vi.advanceTimersByTimeAsync(1); });
    list.mockResolvedValueOnce([{ ...entry, lastSync: { ...queuedRun, status: "running" } }]);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(list).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.getByText("最近同步：运行中")).toBeVisible();
    list.mockResolvedValue([{ ...entry, canResearch: true, lastSync: { ...queuedRun, status: "partial" } }]);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.getByText("最近同步：部分覆盖")).toBeVisible();
    expect(screen.getByText("可研究")).toBeVisible();
    const calls = list.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(list).toHaveBeenCalledTimes(calls);
  });

  it("does not poll terminal failures", async () => {
    const { api, list } = await directory();
    show(api);
    await screen.findByRole("article", { name: "BTCUSDT" });
    vi.useFakeTimers();
    const calls = list.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(list).toHaveBeenCalledTimes(calls);
    expect(screen.queryByText("同步中")).not.toBeInTheDocument();
  });
});
