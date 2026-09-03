import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { DataFreshnessBadge } from "../components/common/DataFreshnessBadge";
import { PageState } from "../components/common/PageState";
import { MockWorkbenchApi } from "../shared/api/mock-workbench-api";
import { mockTradeDraft } from "../shared/mocks/fixtures";
import App from "./App";

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: "candlestick-series",
  ColorType: { Solid: "solid" },
  createChart: () => ({
    addSeries: () => ({ setData: () => undefined }),
    applyOptions: () => undefined,
    remove: () => undefined,
    timeScale: () => ({ fitContent: () => undefined }),
  }),
}));

const observedAt = "2025-01-15T12:00:00Z";
const fetchedAt = "2025-01-15T12:00:05Z";

function renderApp(path = "/") {
  window.history.replaceState({}, "", path);
  const api = new MockWorkbenchApi();
  render(<App api={api} dataMode="mock" />);
  return api;
}

function findDashboardHeading() {
  return screen.findByRole(
    "heading",
    { name: "研究工作台" },
    { timeout: 3_000 },
  );
}

describe("application shell routes", () => {
  beforeAll(() => {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );
  });

  afterAll(() => {
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("renders semantic landmarks and a keyboard-accessible skip link", async () => {
    const user = userEvent.setup();
    renderApp();

    expect(await findDashboardHeading()).toBeVisible();
    expect(
      screen.getByRole("navigation", { name: "主导航" }),
    ).toBeVisible();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");

    await user.tab();

    expect(
      screen.getByRole("link", { name: "跳到主要内容" }),
    ).toHaveFocus();
  });

  it("exposes an accessible control that explicitly collapses the sidebar", async () => {
    const user = userEvent.setup();
    renderApp();

    const collapseButton = screen.getByRole("button", {
      name: "收起主导航",
    });
    expect(collapseButton).toHaveAttribute("aria-expanded", "true");

    await user.click(collapseButton);

    expect(
      screen.getByRole("button", { name: "展开主导航" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById("primary-navigation")).toHaveAttribute(
      "hidden",
    );
  });

  it("exposes the strategy backtest navigation destination", async () => {
    renderApp();

    expect(await findDashboardHeading()).toBeVisible();
    expect(screen.getByRole("link", { name: "策略回测" })).toHaveAttribute(
      "href",
      "/backtests",
    );
  });

  it("reaches every primary destination with focused sidebar links and Enter", async () => {
    const user = userEvent.setup();
    renderApp();

    expect(await findDashboardHeading()).toBeVisible();

    const destinations = [
      {
        linkName: "BTCUSDT 市场",
        path: "/market/BTCUSDT",
        heading: "BTCUSDT 市场详情",
      },
      {
        linkName: "分析报告",
        path: "/reports",
        heading: "分析报告",
      },
      {
        linkName: "模拟盘",
        path: "/paper-trading",
        heading: "模拟盘",
      },
      {
        linkName: "交易日志",
        path: "/trades",
        heading: "交易日志",
      },
      {
        linkName: "复盘统计",
        path: "/analytics",
        heading: "复盘统计",
      },
      {
        linkName: "设置",
        path: "/settings",
        heading: "设置",
      },
    ];

    for (const destination of destinations) {
      const link = screen.getByRole("link", {
        name: destination.linkName,
      });
      link.focus();
      expect(link).toHaveFocus();

      await user.keyboard("{Enter}");

      expect(window.location.pathname).toBe(destination.path);
      expect(
        await screen.findByRole("heading", {
          name: destination.heading,
        }),
      ).toBeVisible();
    }
  });

  it("synchronizes the market navigation label and active state after switching symbols", async () => {
    const user = userEvent.setup();
    renderApp("/market/BTCUSDT");

    await screen.findByRole("heading", { name: "BTCUSDT 市场详情" });
    expect(
      screen.getByRole("link", { name: "BTCUSDT 市场" }),
    ).toHaveClass("app-sidebar__link--active");

    await user.click(screen.getByRole("link", { name: "ETHUSDT" }));

    expect(window.location.pathname).toBe("/market/ETHUSDT");
    expect(
      await screen.findByRole("heading", { name: "ETHUSDT 市场详情" }),
    ).toBeVisible();

    const marketNavigationLink = screen.getByRole("link", {
      name: "ETHUSDT 市场",
    });
    expect(marketNavigationLink).toHaveAttribute("href", "/market/ETHUSDT");
    expect(marketNavigationLink).toHaveClass("app-sidebar__link--active");
    expect(
      screen.queryByRole("link", { name: "BTCUSDT 市场" }),
    ).not.toBeInTheDocument();
  });

  it.each([
    ["/reports/report-btc-001", "报告详情"],
    ["/backtests", "策略回测"],
    ["/trades/new", "新增交易日志"],
    ["/trades/trade-001/edit", "编辑交易日志"],
  ])("maps %s to its declared page", async (path, heading) => {
    renderApp(path);

    expect(
      await screen.findByRole("heading", { name: heading }),
    ).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "页面未找到" }),
    ).not.toBeInTheDocument();
  });

  it("routes the journal list to the working Mock journal instead of a placeholder", async () => {
    renderApp("/trades");

    expect(
      await screen.findByRole("table", { name: "交易日志记录" }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: "新增交易日志" }),
    ).toHaveAttribute("href", "/trades/new");
  });

  it("routes a new journal URL to the working editor", async () => {
    renderApp("/trades/new?linkedAnalysisReportId=report-btc-001");

    expect(
      await screen.findByLabelText("关联分析报告 ID"),
    ).toHaveValue("report-btc-001");
  });

  it("routes analytics to rendered KPI, chart, and calendar data", async () => {
    renderApp("/analytics");

    expect(
      await screen.findByRole("heading", { name: "核心复盘指标" }),
    ).toBeVisible();
    expect(
      screen.getByRole("table", { name: "权益曲线文本数据" }),
    ).toBeVisible();
    expect(
      screen.getByRole("table", { name: "交易日历文本数据" }),
    ).toBeVisible();
  });

  it("renders a clear 404 page and returns to the dashboard without a mouse", async () => {
    const user = userEvent.setup();
    renderApp("/does-not-exist");

    expect(
      await screen.findByRole("heading", { name: "页面未找到" }),
    ).toBeVisible();
    const dashboardLink = screen.getByRole("link", {
      name: "返回研究工作台",
    });
    expect(dashboardLink).toHaveAttribute("href", "/");

    dashboardLink.focus();
    await user.keyboard("{Enter}");

    expect(window.location.pathname).toBe("/");
    expect(await findDashboardHeading()).toBeVisible();
  });

  it("resets the same active MockWorkbenchApi instance exposed by the shell", async () => {
    const user = userEvent.setup();
    const api = new MockWorkbenchApi();
    const seed = await api.listTrades({ page: 1, pageSize: 20 });
    await api.createTrade(mockTradeDraft);
    window.history.replaceState({}, "", "/");

    render(<App api={api} dataMode="mock" />);
    await user.click(
      screen.getByRole("button", { name: "重置 Mock 数据" }),
    );

    await expect(
      api.listTrades({ page: 1, pageSize: 20 }),
    ).resolves.toEqual(seed);
  });

  it("does not expose a live execution label in the application shell", async () => {
    renderApp("/paper-trading");

    await screen.findByRole("heading", { name: "模拟盘" });
    expect(
      screen.queryByText(/真实下单|连接交易所账户|自动执行/),
    ).not.toBeInTheDocument();
  });
});

describe("DataFreshnessBadge", () => {
  it.each([
    ["fresh", "数据正常"],
    ["stale", "数据陈旧"],
    ["missing", "数据缺失"],
    ["failed", "数据获取失败"],
  ] as const)("renders the explicit %s state as visible text", (status, label) => {
    render(
      <DataFreshnessBadge
        status={status}
        source="Deterministic Mock"
        observedAt={observedAt}
        fetchedAt={fetchedAt}
      />,
    );

    expect(screen.getByText(label)).toBeVisible();
  });

  it("uses explicit status instead of inferring freshness from timestamps", () => {
    const { rerender } = render(
      <DataFreshnessBadge
        status="fresh"
        source="Deterministic Mock"
        observedAt={observedAt}
        fetchedAt={fetchedAt}
      />,
    );
    expect(screen.getByText("数据正常")).toBeVisible();

    rerender(
      <DataFreshnessBadge
        status="stale"
        source="Deterministic Mock"
        observedAt={observedAt}
        fetchedAt={fetchedAt}
      />,
    );

    expect(screen.getByText("数据陈旧")).toBeVisible();
    expect(screen.queryByText("数据正常")).not.toBeInTheDocument();
  });
});

describe("PageState", () => {
  it.each([
    ["loading", "正在加载数据"],
    ["empty", "暂无数据"],
    ["error", "数据加载失败"],
    ["unavailable", "数据暂不可用"],
  ] as const)("renders the standardized %s state", (state, label) => {
    render(<PageState state={state} />);

    expect(screen.getByText(label)).toBeVisible();
  });

  it("announces an error and preserves its safe user-facing detail", () => {
    render(
      <PageState
        state="error"
        message="无法读取工作台数据，请稍后重试。"
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "无法读取工作台数据，请稍后重试。",
    );
  });
});
