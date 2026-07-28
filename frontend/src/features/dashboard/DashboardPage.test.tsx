import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppProviders } from "../../app/providers";
import type { DashboardSnapshot } from "../../domain/market";
import { MockWorkbenchApi } from "../../shared/api/mock-workbench-api";
import { WorkbenchHttpError } from "../../shared/api/http-transport";
import { DashboardPage } from "./DashboardPage";

class PendingDashboardApi extends MockWorkbenchApi {
  override getDashboard(): Promise<DashboardSnapshot> {
    return new Promise(() => undefined);
  }
}

class FailingDashboardApi extends MockWorkbenchApi {
  override getDashboard(): Promise<DashboardSnapshot> {
    return Promise.reject(
      new Error("private upstream detail must not reach the user"),
    );
  }
}

class UnavailablePublicDashboardApi extends MockWorkbenchApi {
  override getDashboard(): Promise<DashboardSnapshot> {
    return Promise.reject(
      new WorkbenchHttpError(
        503,
        "market_data_unavailable",
        "公开行情服务不可用",
      ),
    );
  }
}

function renderDashboard(api: MockWorkbenchApi = new MockWorkbenchApi()) {
  render(
    <AppProviders api={api}>
      <DashboardPage />
    </AppProviders>,
  );
}

describe("DashboardPage", () => {
  it("renders the standard loading state while dashboard data is pending", () => {
    renderDashboard(new PendingDashboardApi());

    expect(screen.getByText("正在加载数据")).toBeVisible();
    expect(screen.getByRole("status")).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("renders a safe standard error state when dashboard loading fails", async () => {
    renderDashboard(new FailingDashboardApi());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("数据加载失败");
    expect(alert).toHaveTextContent("无法读取研究工作台数据，请稍后重试。");
    expect(alert).not.toHaveTextContent("private upstream detail");
  });

  it("renders an explicit public-market error without upstream details", async () => {
    renderDashboard(new UnavailablePublicDashboardApi());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("公开行情暂不可用");
    expect(alert).not.toHaveTextContent("公开行情服务不可用");
  });

  it("shows the explicit stale state and its source timestamps", async () => {
    renderDashboard();

    const ethCard = await screen.findByRole("article", {
      name: "ETHUSDT 市场摘要",
    });
    expect(
      within(ethCard).getByRole("status", {
        name: "数据新鲜度：数据陈旧",
      }),
    ).toBeVisible();
    expect(
      within(ethCard).getByText("来源：Deterministic Mock"),
    ).toBeVisible();
    expect(
      within(ethCard).getByText("2025-01-15T11:45:00Z"),
    ).toBeVisible();
    expect(
      within(ethCard).getByText("2025-01-15T12:00:05Z"),
    ).toBeVisible();
  });

  it.each([
    {
      symbol: "BTCUSDT",
      price: "67,890.12",
      change: "+1.25%",
      volume: "3,250,000,000.50",
      fundingRate: "+0.0100%",
      openInterest: "1,280,000,000",
      observedAt: "2025-01-15T12:00:00Z",
      fetchedAt: "2025-01-15T12:00:05Z",
    },
    {
      symbol: "ETHUSDT",
      price: "3,456.78",
      change: "-0.75%",
      volume: "1,850,000,000",
      fundingRate: "-0.0050%",
      openInterest: "720,000,000",
      observedAt: "2025-01-15T11:45:00Z",
      fetchedAt: "2025-01-15T12:00:05Z",
    },
  ])(
    "renders formatted $symbol metrics while preserving source metadata",
    async ({
      symbol,
      price,
      change,
      volume,
      fundingRate,
      openInterest,
      observedAt,
      fetchedAt,
    }) => {
      renderDashboard();

      const card = await screen.findByRole("article", {
        name: `${symbol} 市场摘要`,
      });
      expect(within(card).getByText("价格")).toBeVisible();
      expect(within(card).getByText(price)).toBeVisible();
      expect(within(card).getByText("24 小时涨跌")).toBeVisible();
      expect(within(card).getByText(change)).toBeVisible();
      expect(within(card).getByText("24 小时成交量")).toBeVisible();
      expect(within(card).getByText(volume)).toBeVisible();
      expect(within(card).getByText("资金费率")).toBeVisible();
      expect(within(card).getByText(fundingRate)).toBeVisible();
      expect(within(card).getByText("未平仓量")).toBeVisible();
      expect(within(card).getByText(openInterest)).toBeVisible();
      expect(
        within(card).getByText("来源：Deterministic Mock"),
      ).toBeVisible();
      expect(within(card).getByText(observedAt)).toBeVisible();
      expect(within(card).getByText(fetchedAt)).toBeVisible();
    },
  );

  it("renders recent research and news with their explicit data times", async () => {
    renderDashboard();

    expect(
      await screen.findByText("BTCUSDT 离线研究样例"),
    ).toBeVisible();
    expect(screen.getByText("2025-01-15T10:00:00Z")).toBeVisible();
    expect(screen.getByText("2025-01-15T09:55:00Z")).toBeVisible();
    expect(
      screen.getByText("示例市场基础设施维护公告"),
    ).toBeVisible();
    expect(screen.getByText("2025-01-14T08:00:00Z")).toBeVisible();
    expect(screen.getByText("2025-01-15T12:05:00Z")).toBeVisible();
  });
});
