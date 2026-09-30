import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import App from "../../app/App";
import {
  HybridWorkbenchApi,
  type RemoteWorkbenchApi,
} from "../api/hybrid-workbench-api";
import { HttpWorkbenchApi } from "../api/http-workbench-api";
import { MockWorkbenchApi } from "../api/mock-workbench-api";
import { mockTradeDraft } from "./fixtures";

describe("Mock mode controls", () => {
  it("renders the visible mode label and resets the active Mock API in memory", async () => {
    const user = userEvent.setup();
    const api = new MockWorkbenchApi();
    const seed = await api.listTrades({ page: 1, pageSize: 20 });
    await api.createTrade(mockTradeDraft);
    const changed = await api.listTrades({ page: 1, pageSize: 20 });
    expect(changed.total).toBe(seed.total + 1);

    render(<App dataMode="mock" api={api} />);

    expect(screen.getByText("Mock 数据模式")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "重置 Mock 数据" }));
    await expect(
      api.listTrades({ page: 1, pageSize: 20 }),
    ).resolves.toEqual(seed);
  });

  it("does not render Mock controls in API mode", () => {
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
    });
    render(<App dataMode="api" api={api} />);

    expect(screen.queryByText("Mock 数据模式")).not.toBeInTheDocument();
  });

  it("labels local market, report, journal, and analytics data", () => {
    const marketApi: RemoteWorkbenchApi = {
      listMarketSummaries: () => Promise.resolve([]),
      getMarket: () => Promise.reject(new Error("not called by the shell")),
      listReports: () =>
        Promise.resolve({ items: [], page: 1, pageSize: 20, total: 0 }),
      getReport: () => Promise.reject(new Error("not called by the shell")),
      startReport: () => Promise.reject(new Error("not called by the shell")),
      retryReport: () => Promise.reject(new Error("not called by the shell")),
      startTechnicalReport: () => Promise.reject(new Error("not called by the shell")),
      listTechnicalReports: () => Promise.reject(new Error("not called by the shell")),
      getTechnicalReport: () => Promise.reject(new Error("not called by the shell")),
      subscribeReport: () => () => undefined,
      listTrades: () => Promise.reject(new Error("not called by the shell")),
      createTrade: () => Promise.reject(new Error("not called by the shell")),
      updateTrade: () => Promise.reject(new Error("not called by the shell")),
      getAnalytics: () => Promise.reject(new Error("not called by the shell")),
      startBacktest: () => Promise.reject(new Error("not called by the shell")),
      listBacktests: () => Promise.reject(new Error("not called by the shell")),
      getBacktest: () => Promise.reject(new Error("not called by the shell")),
      createPaperAccount: () =>
        Promise.reject(new Error("not called by the shell")),
      listPaperAccounts: () =>
        Promise.reject(new Error("not called by the shell")),
      getPaperAccount: () =>
        Promise.reject(new Error("not called by the shell")),
      getPaperPerformance: () =>
        Promise.reject(new Error("not called by the shell")),
      submitPaperManualIntent: () =>
        Promise.reject(new Error("not called by the shell")),
      evaluatePaperStrategy: () =>
        Promise.reject(new Error("not called by the shell")),
      archivePaperAccount: () =>
        Promise.reject(new Error("not called by the shell")),
    };
    const api = new HybridWorkbenchApi(new MockWorkbenchApi(), marketApi);

    render(<App dataMode="market-api" api={api} />);

    expect(screen.getByText("公开市场数据模式")).toBeVisible();
    expect(
      screen.getByText("市场、报告、交易日志与统计使用本地 API；资讯仍为 Mock"),
    ).toBeVisible();
    expect(screen.queryByText("重置 Mock 数据")).not.toBeInTheDocument();
  });
});
