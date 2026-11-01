import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers";
import type { ResearchSymbolEntry } from "../../domain/research-symbol";
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
