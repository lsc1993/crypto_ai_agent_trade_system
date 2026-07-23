import {
  act,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  Link,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppProviders } from "../../app/providers";
import type { Page, Symbol } from "../../domain/primitives";
import {
  analysisReportSchema,
  analysisReportSummarySchema,
  analysisStreamEventSchema,
  type AnalysisReport,
  type AnalysisReportSummary,
  type AnalysisStreamEvent,
  type ReportFilters,
  type ReportStatus,
} from "../../domain/report";
import { MockWorkbenchApi } from "../../shared/api/mock-workbench-api";
import { mockReports } from "../../shared/mocks/fixtures";
import { ReportDetailPage } from "./ReportDetailPage";
import { ReportGenerator } from "./ReportGenerator";
import { ReportListPage } from "./ReportListPage";

const statusLabels = [
  ["queued", "排队中"],
  ["running", "分析中"],
  ["completed", "已完成"],
  ["degraded", "已降级"],
  ["failed", "失败"],
] as const satisfies ReadonlyArray<readonly [ReportStatus, string]>;

function seedReport(): AnalysisReport {
  const seed = mockReports[0];
  if (seed === undefined) {
    throw new Error("Report fixture is missing");
  }
  return analysisReportSchema.parse(seed);
}

class EveryStatusReportsApi extends MockWorkbenchApi {
  override listReports(
    filters: ReportFilters,
  ): Promise<Page<AnalysisReportSummary>> {
    const seed = seedReport();
    const items = statusLabels.map(([status]) =>
      analysisReportSummarySchema.parse({
        ...seed,
        id: `report-${status}`,
        analysisId: `analysis-${status}`,
        status,
        title: `${status} 状态研究样例`,
      }),
    );
    return Promise.resolve({
      items,
      page: filters.page ?? 1,
      pageSize: filters.pageSize ?? 20,
      total: items.length,
    });
  }
}

class PendingReportListApi extends EveryStatusReportsApi {
  override listReports(): Promise<Page<AnalysisReportSummary>> {
    return new Promise(() => undefined);
  }
}

class FailingReportListApi extends EveryStatusReportsApi {
  override listReports(): Promise<Page<AnalysisReportSummary>> {
    return Promise.reject(
      new Error("private report list detail must stay hidden"),
    );
  }
}

class ControlledReportDetailApi extends MockWorkbenchApi {
  readonly retriedReportIds: string[] = [];
  readonly subscribedAnalysisIds: string[] = [];
  readonly unsubscribedAnalysisIds: string[] = [];

  private retrySequence = 0;
  private readonly subscribers = new Map<
    string,
    (event: AnalysisStreamEvent) => void
  >();

  override getReport(reportId: string): Promise<AnalysisReport> {
    if (reportId.length === 0) {
      throw new Error("Report ID is required");
    }
    return Promise.resolve(seedReport());
  }

  override retryReport(
    reportId: string,
  ): Promise<{ analysisId: string }> {
    this.retriedReportIds.push(reportId);
    this.retrySequence += 1;
    return Promise.resolve({
      analysisId: `analysis-retry-fresh-${this.retrySequence}`,
    });
  }

  override subscribeReport(
    analysisId: string,
    onEvent: (event: AnalysisStreamEvent) => void,
  ): () => void {
    this.subscribedAnalysisIds.push(analysisId);
    this.subscribers.set(analysisId, onEvent);
    return () => {
      this.unsubscribedAnalysisIds.push(analysisId);
      this.subscribers.delete(analysisId);
    };
  }

  emit(analysisId: string, status: ReportStatus): void {
    const subscriber = this.subscribers.get(analysisId);
    if (subscriber === undefined) {
      throw new Error(`No subscriber registered for ${analysisId}`);
    }
    subscriber(
      analysisStreamEventSchema.parse({
        analysisId,
        symbol: "BTCUSDT" satisfies Symbol,
        status,
        occurredAt: "2025-02-01T01:00:00Z",
        message: `研究生命周期状态：${status}`,
      }),
    );
  }
}

class ControlledReportGeneratorApi extends MockWorkbenchApi {
  readonly startedSymbols: Symbol[] = [];
  readonly subscribedAnalysisIds: string[] = [];
  readonly unsubscribedAnalysisIds: string[] = [];

  private startSequence = 0;
  private readonly subscribers = new Map<
    string,
    (event: AnalysisStreamEvent) => void
  >();

  override startReport(input: {
    symbol: Symbol;
  }): Promise<{ analysisId: string }> {
    this.startedSymbols.push(input.symbol);
    this.startSequence += 1;
    return Promise.resolve({
      analysisId: `analysis-start-fresh-${this.startSequence}`,
    });
  }

  override subscribeReport(
    analysisId: string,
    onEvent: (event: AnalysisStreamEvent) => void,
  ): () => void {
    this.subscribedAnalysisIds.push(analysisId);
    this.subscribers.set(analysisId, onEvent);
    return () => {
      this.unsubscribedAnalysisIds.push(analysisId);
      this.subscribers.delete(analysisId);
    };
  }

  emit(analysisId: string, status: ReportStatus): void {
    const subscriber = this.subscribers.get(analysisId);
    if (subscriber === undefined) {
      throw new Error(`No subscriber registered for ${analysisId}`);
    }
    subscriber(
      analysisStreamEventSchema.parse({
        analysisId,
        symbol: "BTCUSDT",
        status,
        occurredAt: "2025-02-01T01:00:00Z",
        message: `研究生命周期状态：${status}`,
      }),
    );
  }
}

class DeferredReportGeneratorApi extends ControlledReportGeneratorApi {
  private resolveStart:
    | ((value: { analysisId: string }) => void)
    | null = null;

  override startReport(input: {
    symbol: Symbol;
  }): Promise<{ analysisId: string }> {
    this.startedSymbols.push(input.symbol);
    return new Promise((resolve) => {
      this.resolveStart = resolve;
    });
  }

  finishStart(analysisId: string): void {
    const resolve = this.resolveStart;
    if (resolve === null) {
      throw new Error("No pending report start");
    }
    this.resolveStart = null;
    resolve({ analysisId });
  }
}

class PendingReportDetailApi extends ControlledReportDetailApi {
  override getReport(): Promise<AnalysisReport> {
    return new Promise(() => undefined);
  }
}

class FailingReportDetailApi extends ControlledReportDetailApi {
  override getReport(): Promise<AnalysisReport> {
    return Promise.reject(
      new Error("private report service detail must stay hidden"),
    );
  }
}

class FailedReportDetailApi extends ControlledReportDetailApi {
  override getReport(): Promise<AnalysisReport> {
    return Promise.resolve(
      analysisReportSchema.parse({
        ...seedReport(),
        status: "failed",
      }),
    );
  }
}

class RoutedReportDetailApi extends ControlledReportDetailApi {
  override getReport(reportId: string): Promise<AnalysisReport> {
    return Promise.resolve(
      analysisReportSchema.parse({
        ...seedReport(),
        id: reportId,
        analysisId: `analysis-for-${reportId}`,
        status: "failed",
      }),
    );
  }
}

class DeferredRoutedReportDetailApi extends RoutedReportDetailApi {
  private resolveRetry:
    | ((value: { analysisId: string }) => void)
    | null = null;

  override retryReport(
    reportId: string,
  ): Promise<{ analysisId: string }> {
    this.retriedReportIds.push(reportId);
    return new Promise((resolve) => {
      this.resolveRetry = resolve;
    });
  }

  finishRetry(analysisId: string): void {
    const resolve = this.resolveRetry;
    if (resolve === null) {
      throw new Error("No pending report retry");
    }
    this.resolveRetry = null;
    resolve({ analysisId });
  }
}

function LocationProbe() {
  const location = useLocation();
  return (
    <output aria-label="交易日志预填导航">
      {JSON.stringify({
        pathname: location.pathname,
        search: location.search,
        state: location.state === null ? null : "present",
      })}
    </output>
  );
}

function renderReportDetail(
  api: MockWorkbenchApi = new ControlledReportDetailApi(),
) {
  window.history.replaceState({}, "", "/reports/report-btc-001");
  return render(
    <AppProviders api={api}>
      <Routes>
        <Route
          path="/reports/:reportId"
          element={<ReportDetailPage />}
        />
        <Route path="/trades/new" element={<LocationProbe />} />
      </Routes>
    </AppProviders>,
  );
}

describe("ReportListPage", () => {
  it("renders the standard loading state while report summaries are pending", () => {
    window.history.replaceState({}, "", "/reports");
    render(
      <AppProviders api={new PendingReportListApi()}>
        <Routes>
          <Route path="/reports" element={<ReportListPage />} />
        </Routes>
      </AppProviders>,
    );

    expect(screen.getByText("正在加载数据")).toBeVisible();
    expect(screen.getByRole("status")).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("renders a safe error without exposing list service details", async () => {
    window.history.replaceState({}, "", "/reports");
    render(
      <AppProviders api={new FailingReportListApi()}>
        <Routes>
          <Route path="/reports" element={<ReportListPage />} />
        </Routes>
      </AppProviders>,
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("无法读取分析报告，请稍后重试。");
    expect(alert).not.toHaveTextContent("private report list detail");
  });

  it("renders every frozen report lifecycle status as visible Chinese text", async () => {
    window.history.replaceState({}, "", "/reports");
    render(
      <AppProviders api={new EveryStatusReportsApi()}>
        <Routes>
          <Route path="/reports" element={<ReportListPage />} />
        </Routes>
      </AppProviders>,
    );

    expect(
      await screen.findByRole("heading", { name: "分析报告" }),
    ).toBeVisible();
    for (const [status, label] of statusLabels) {
      const report = screen.getByRole("article", {
        name: `${status} 状态研究样例`,
      });
      expect(within(report).getByText(label)).toBeVisible();
      expect(within(report).getByText(`analysis-${status}`)).toBeVisible();
    }
    expect(
      screen.getByRole("heading", { name: "历史报告" }),
    ).toBeVisible();
    expect(screen.queryByText("REPORT HISTORY")).not.toBeInTheDocument();
  });
});

describe("ReportGenerator", () => {
  it("uses a fresh analysis ID and replaces the previous lifecycle subscription", async () => {
    const user = userEvent.setup();
    const api = new ControlledReportGeneratorApi();
    render(
      <AppProviders api={api}>
        <ReportGenerator symbol="BTCUSDT" />
      </AppProviders>,
    );

    const generate = screen.getByRole("button", {
      name: "生成 AI 研究报告",
    });
    await user.click(generate);
    await waitFor(() => {
      expect(api.startedSymbols).toEqual(["BTCUSDT"]);
      expect(api.subscribedAnalysisIds).toEqual([
        "analysis-start-fresh-1",
      ]);
    });

    for (const [status, label] of statusLabels.slice(0, 3)) {
      act(() => {
        api.emit("analysis-start-fresh-1", status);
      });
      expect(screen.getByRole("status")).toHaveTextContent(label);
    }

    await user.click(generate);
    await waitFor(() => {
      expect(api.subscribedAnalysisIds).toEqual([
        "analysis-start-fresh-1",
        "analysis-start-fresh-2",
      ]);
    });
    expect(api.unsubscribedAnalysisIds).toContain(
      "analysis-start-fresh-1",
    );
  });

  it.each(["completed", "degraded", "failed"] as const)(
    "unsubscribes immediately when the lifecycle reaches %s",
    async (terminalStatus) => {
      const user = userEvent.setup();
      const api = new ControlledReportGeneratorApi();
      render(
        <AppProviders api={api}>
          <ReportGenerator symbol="BTCUSDT" />
        </AppProviders>,
      );

      await user.click(
        screen.getByRole("button", {
          name: "生成 AI 研究报告",
        }),
      );
      await waitFor(() => {
        expect(api.subscribedAnalysisIds).toEqual([
          "analysis-start-fresh-1",
        ]);
      });

      act(() => {
        api.emit("analysis-start-fresh-1", terminalStatus);
      });

      await waitFor(() => {
        expect(api.unsubscribedAnalysisIds).toEqual([
          "analysis-start-fresh-1",
        ]);
      });
    },
  );

  it("cleans up the active lifecycle subscription on unmount", async () => {
    const user = userEvent.setup();
    const api = new ControlledReportGeneratorApi();
    const view = render(
      <AppProviders api={api}>
        <ReportGenerator symbol="BTCUSDT" />
      </AppProviders>,
    );

    await user.click(
      screen.getByRole("button", {
        name: "生成 AI 研究报告",
      }),
    );
    await waitFor(() => {
      expect(api.subscribedAnalysisIds).toEqual([
        "analysis-start-fresh-1",
      ]);
    });

    view.unmount();

    expect(api.unsubscribedAnalysisIds).toEqual([
      "analysis-start-fresh-1",
    ]);
  });

  it("does not subscribe when a delayed start succeeds after unmount", async () => {
    const user = userEvent.setup();
    const api = new DeferredReportGeneratorApi();
    const view = render(
      <AppProviders api={api}>
        <ReportGenerator symbol="BTCUSDT" />
      </AppProviders>,
    );

    await user.click(
      screen.getByRole("button", {
        name: "生成 AI 研究报告",
      }),
    );
    expect(api.startedSymbols).toEqual(["BTCUSDT"]);
    view.unmount();

    await act(async () => {
      api.finishStart("analysis-after-unmount");
      await Promise.resolve();
    });

    expect(api.subscribedAnalysisIds).toEqual([]);
  });
});

describe("ReportDetailPage", () => {
  it("renders the standard loading state while report detail is pending", () => {
    renderReportDetail(new PendingReportDetailApi());

    expect(screen.getByText("正在加载数据")).toBeVisible();
    expect(screen.getByRole("status")).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("renders a safe error without exposing service details", async () => {
    renderReportDetail(new FailingReportDetailApi());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("数据加载失败");
    expect(alert).toHaveTextContent("无法读取报告详情，请稍后重试。");
    expect(alert).not.toHaveTextContent("private report service");
  });

  it("keeps facts, inferences, risks, and limitations in distinct labelled regions", async () => {
    renderReportDetail();

    const facts = await screen.findByRole("region", {
      name: "事实观察",
    });
    const inferences = screen.getByRole("region", {
      name: "分析推断",
    });
    const risks = screen.getByRole("region", { name: "风险标记" });
    const limitations = screen.getByRole("region", {
      name: "分析限制",
    });

    expect(facts).toHaveTextContent(
      "示例价格和成交量来自固定 Mock 数据。",
    );
    expect(inferences).toHaveTextContent(
      "该段落仅演示推断与事实分离。",
    );
    expect(risks).toHaveTextContent("固定样例不反映当前市场。");
    expect(limitations).toHaveTextContent(
      "没有访问交易所、账户或模型服务。",
    );
    expect(facts).not.toBe(inferences);
    expect(risks).not.toBe(limitations);
  });

  it("renders immutable evidence metadata and a secured external source link", async () => {
    renderReportDetail();

    const evidenceList = await screen.findByRole("region", {
      name: "证据列表",
    });
    const evidence = within(evidenceList).getByRole("article", {
      name: "证据 evidence-btc-001",
    });
    expect(evidence).toHaveTextContent(
      "不可变证据 ID：evidence-btc-001",
    );
    expect(evidence).toHaveTextContent("来源：Mock Research Feed");
    expect(evidence).toHaveTextContent(
      "观察时间：2025-01-15T09:55:00Z",
    );

    const sourceLink = within(evidence).getByRole("link", {
      name: "查看原始来源",
    });
    expect(sourceLink).toHaveAttribute(
      "href",
      "https://example.com/mock-evidence-btc-001",
    );
    expect(sourceLink).toHaveAttribute("target", "_blank");
    expect(sourceLink).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
  });

  it("retries the original report with a fresh analysis lifecycle", async () => {
    const user = userEvent.setup();
    const api = new FailedReportDetailApi();
    renderReportDetail(api);

    expect(await screen.findByText("analysis-btc-001")).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "以新分析任务重试" }),
    );

    await waitFor(() => {
      expect(api.retriedReportIds).toEqual(["report-btc-001"]);
      expect(api.subscribedAnalysisIds).toEqual([
        "analysis-retry-fresh-1",
      ]);
    });
    expect(api.subscribedAnalysisIds).not.toContain("analysis-btc-001");
    expect(screen.getByText("analysis-btc-001")).toBeVisible();
    expect(screen.getByText("analysis-retry-fresh-1")).toBeVisible();

    for (const [status, label] of statusLabels.slice(0, 3)) {
      act(() => {
        api.emit("analysis-retry-fresh-1", status);
      });
      expect(screen.getByRole("status")).toHaveTextContent(label);
    }
  });

  it.each(["completed", "degraded", "failed"] as const)(
    "unsubscribes retry lifecycle immediately when it reaches %s",
    async (terminalStatus) => {
      const user = userEvent.setup();
      const api = new FailedReportDetailApi();
      renderReportDetail(api);

      await screen.findByText("analysis-btc-001");
      await user.click(
        screen.getByRole("button", { name: "以新分析任务重试" }),
      );
      await waitFor(() => {
        expect(api.subscribedAnalysisIds).toEqual([
          "analysis-retry-fresh-1",
        ]);
      });

      act(() => {
        api.emit("analysis-retry-fresh-1", terminalStatus);
      });

      await waitFor(() => {
        expect(api.unsubscribedAnalysisIds).toEqual([
          "analysis-retry-fresh-1",
        ]);
      });
    },
  );

  it("unsubscribes and resets stale retry state when reportId changes in place", async () => {
    const user = userEvent.setup();
    const api = new RoutedReportDetailApi();
    window.history.replaceState({}, "", "/reports/report-btc-001");
    render(
      <AppProviders api={api}>
        <Link to="/reports/report-eth-001">切换报告</Link>
        <Routes>
          <Route
            path="/reports/:reportId"
            element={<ReportDetailPage />}
          />
        </Routes>
      </AppProviders>,
    );

    await screen.findByText("report-btc-001");
    await user.click(
      screen.getByRole("button", { name: "以新分析任务重试" }),
    );
    await waitFor(() => {
      expect(api.subscribedAnalysisIds).toEqual([
        "analysis-retry-fresh-1",
      ]);
    });
    act(() => {
      api.emit("analysis-retry-fresh-1", "running");
    });
    expect(screen.getByRole("status")).toHaveTextContent("分析中");

    await user.click(screen.getByRole("link", { name: "切换报告" }));

    expect(await screen.findByText("report-eth-001")).toBeVisible();
    expect(api.unsubscribedAnalysisIds).toEqual([
      "analysis-retry-fresh-1",
    ]);
    expect(
      screen.queryByText("analysis-retry-fresh-1"),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("cleans up the active retry subscription on unmount", async () => {
    const user = userEvent.setup();
    const api = new FailedReportDetailApi();
    const view = renderReportDetail(api);

    await screen.findByText("analysis-btc-001");
    await user.click(
      screen.getByRole("button", { name: "以新分析任务重试" }),
    );
    await waitFor(() => {
      expect(api.subscribedAnalysisIds).toEqual([
        "analysis-retry-fresh-1",
      ]);
    });

    view.unmount();

    expect(api.unsubscribedAnalysisIds).toEqual([
      "analysis-retry-fresh-1",
    ]);
  });

  it("does not subscribe when a delayed retry succeeds after switching reports", async () => {
    const user = userEvent.setup();
    const api = new DeferredRoutedReportDetailApi();
    window.history.replaceState({}, "", "/reports/report-btc-001");
    render(
      <AppProviders api={api}>
        <Link to="/reports/report-eth-001">切换报告</Link>
        <Routes>
          <Route
            path="/reports/:reportId"
            element={<ReportDetailPage />}
          />
        </Routes>
      </AppProviders>,
    );

    await screen.findByText("report-btc-001");
    await user.click(
      screen.getByRole("button", { name: "以新分析任务重试" }),
    );
    expect(api.retriedReportIds).toEqual(["report-btc-001"]);
    await user.click(screen.getByRole("link", { name: "切换报告" }));
    expect(await screen.findByText("report-eth-001")).toBeVisible();

    await act(async () => {
      api.finishRetry("analysis-after-switch");
      await Promise.resolve();
    });

    expect(api.subscribedAnalysisIds).toEqual([]);
    expect(
      screen.queryByText("analysis-after-switch"),
    ).not.toBeInTheDocument();
  });

  it("does not subscribe when a delayed retry succeeds after unmount", async () => {
    const user = userEvent.setup();
    const api = new DeferredRoutedReportDetailApi();
    const view = renderReportDetail(api);

    await screen.findByText("report-btc-001");
    await user.click(
      screen.getByRole("button", { name: "以新分析任务重试" }),
    );
    expect(api.retriedReportIds).toEqual(["report-btc-001"]);
    view.unmount();

    await act(async () => {
      api.finishRetry("analysis-after-unmount");
      await Promise.resolve();
    });

    expect(api.subscribedAnalysisIds).toEqual([]);
  });

  it("hands off only linkedAnalysisReportId when creating a trade journal", async () => {
    const user = userEvent.setup();
    renderReportDetail();

    await user.click(
      await screen.findByRole("link", {
        name: "基于此分析创建交易日志",
      }),
    );

    expect(window.location.pathname).toBe("/trades/new");
    expect([...new URLSearchParams(window.location.search).entries()]).toEqual(
      [["linkedAnalysisReportId", "report-btc-001"]],
    );
    const navigation = JSON.parse(
      screen.getByLabelText("交易日志预填导航").textContent ?? "{}",
    ) as Record<string, unknown>;
    expect(navigation).toEqual({
      pathname: "/trades/new",
      search: "?linkedAnalysisReportId=report-btc-001",
      state: null,
    });
    expect(window.location.search).not.toMatch(
      /summary|evidence|recommendation|facts|inferences|risks|limitations/i,
    );
  });
});
