import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AppProviders } from "../../app/providers";
import {
  analyticsSnapshotSchema,
  type AnalyticsFilters,
  type AnalyticsSnapshot,
} from "../../domain/analytics";
import { MockWorkbenchApi } from "../../shared/api/mock-workbench-api";
import { AnalyticsPage } from "./AnalyticsPage";

function createAnalyticsSnapshot(
  overrides: Partial<AnalyticsSnapshot> = {},
): AnalyticsSnapshot {
  return analyticsSnapshotSchema.parse({
    netPnl: "9.40",
    winRate: "0.625",
    profitFactor: "1.75",
    expectancy: "2.35",
    maxDrawdown: "-4.00",
    equityCurve: [
      {
        at: "2025-01-10T00:00:00Z",
        equity: "4.20",
        netPnl: "4.20",
      },
      {
        at: "2025-01-11T00:00:00Z",
        equity: "9.40",
        netPnl: "9.40",
      },
    ],
    tradeCalendar: [
      {
        at: "2025-01-11T00:00:00Z",
        netPnl: "9.40",
        tradeCount: 1,
      },
    ],
    generatedAt: "2025-01-15T12:05:00Z",
    ...overrides,
  });
}

class RecordingAnalyticsApi extends MockWorkbenchApi {
  readonly analyticsInputs: AnalyticsFilters[] = [];

  constructor(private readonly snapshot: AnalyticsSnapshot) {
    super();
  }

  override getAnalytics(
    filters: AnalyticsFilters,
  ): Promise<AnalyticsSnapshot> {
    this.analyticsInputs.push({ ...filters });
    return Promise.resolve(this.snapshot);
  }
}

class PendingAnalyticsApi extends MockWorkbenchApi {
  override getAnalytics(): Promise<AnalyticsSnapshot> {
    return new Promise(() => undefined);
  }
}

class FailingAnalyticsApi extends MockWorkbenchApi {
  override getAnalytics(): Promise<AnalyticsSnapshot> {
    return Promise.reject(
      new Error("private analytics service detail must stay hidden"),
    );
  }
}

function renderAnalytics(api: MockWorkbenchApi): void {
  window.history.replaceState({}, "", "/analytics");
  render(
    <AppProviders api={api}>
      <AnalyticsPage />
    </AppProviders>,
  );
}

describe("AnalyticsPage", () => {
  it("renders the standard loading state while the analytics snapshot is pending", () => {
    renderAnalytics(new PendingAnalyticsApi());

    expect(screen.getByText("正在加载数据")).toBeVisible();
    expect(screen.getByRole("status")).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("renders a safe error without exposing analytics service details", async () => {
    renderAnalytics(new FailingAnalyticsApi());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("无法读取复盘统计，请稍后重试。");
    expect(alert).not.toHaveTextContent("private analytics service detail");
  });

  it("renders the standard empty state when the snapshot has no curve or calendar data", async () => {
    renderAnalytics(
      new RecordingAnalyticsApi(
        createAnalyticsSnapshot({ equityCurve: [], tradeCalendar: [] }),
      ),
    );

    expect(
      await screen.findByText("当前筛选条件下暂无可复盘的交易统计。"),
    ).toBeVisible();
  });

  it("validates and sends the selected analytics filters through WorkbenchApi", async () => {
    const user = userEvent.setup();
    const api = new RecordingAnalyticsApi(createAnalyticsSnapshot());
    renderAnalytics(api);

    await screen.findByRole("heading", { name: "复盘统计" });
    fireEvent.change(screen.getByLabelText("标的"), {
      target: { value: "BTCUSDT" },
    });
    fireEvent.change(screen.getByLabelText("方向"), {
      target: { value: "long" },
    });
    fireEvent.change(screen.getByLabelText("周期"), {
      target: { value: "short_term" },
    });
    fireEvent.change(screen.getByLabelText("标签"), {
      target: { value: "复盘样例" },
    });
    fireEvent.change(screen.getByLabelText("开始时间（UTC）"), {
      target: { value: "2025-01-01T00:00:00Z" },
    });
    fireEvent.change(screen.getByLabelText("结束时间（UTC）"), {
      target: { value: "2025-01-31T23:59:59Z" },
    });
    await user.click(screen.getByRole("button", { name: "应用筛选条件" }));

    const expectedFilters = {
      symbol: "BTCUSDT",
      direction: "long",
      horizon: "short_term",
      label: "复盘样例",
      from: "2025-01-01T00:00:00Z",
      to: "2025-01-31T23:59:59Z",
    } satisfies AnalyticsFilters;

    await waitFor(() => {
      expect(api.analyticsInputs).toEqual([{}, expectedFilters]);
    });
  });

  it("renders the empty state after an unmatched Mock filter is applied", async () => {
    const user = userEvent.setup();
    renderAnalytics(new MockWorkbenchApi());

    await screen.findByRole("heading", { name: "复盘统计" });
    fireEvent.change(screen.getByLabelText("标的"), {
      target: { value: "ETHUSDT" },
    });
    await user.click(screen.getByRole("button", { name: "应用筛选条件" }));

    expect(
      await screen.findByText("当前筛选条件下暂无可复盘的交易统计。"),
    ).toBeVisible();
  });

  it("rejects a non-UTC filter value without issuing another analytics request", async () => {
    const user = userEvent.setup();
    const api = new RecordingAnalyticsApi(createAnalyticsSnapshot());
    renderAnalytics(api);

    await screen.findByRole("heading", { name: "复盘统计" });
    fireEvent.change(screen.getByLabelText("开始时间（UTC）"), {
      target: { value: "2025-01-01T08:00:00+08:00" },
    });
    await user.click(screen.getByRole("button", { name: "应用筛选条件" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "筛选时间必须使用 UTC RFC3339 Z 格式。",
    );
    expect(api.analyticsInputs).toEqual([{}]);
  });

  it("uses Chinese user-facing labels throughout the analytics panels", async () => {
    renderAnalytics(new RecordingAnalyticsApi(createAnalyticsSnapshot()));

    expect(await screen.findByText("模拟复盘")).toBeVisible();
    expect(await screen.findByText("模拟统计")).toBeVisible();
    expect(screen.getByText("仅用于显示")).toBeVisible();
    expect(screen.getByText("按 UTC 日期")).toBeVisible();
    expect(screen.queryByText("MOCK REVIEW")).not.toBeInTheDocument();
    expect(screen.queryByText("MOCK ANALYTICS")).not.toBeInTheDocument();
    expect(screen.queryByText("DISPLAY ONLY")).not.toBeInTheDocument();
    expect(screen.queryByText("UTC CALENDAR")).not.toBeInTheDocument();
    expect(screen.queryByText(/Mock/)).not.toBeInTheDocument();
  });
});
