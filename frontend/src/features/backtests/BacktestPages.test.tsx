import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppProviders } from "../../app/providers";
import {
  backtestRunDetailSchema,
  type BacktestRequest,
  type BacktestRunDetail,
  type BacktestRunSummary,
} from "../../domain/backtest";
import type { Page } from "../../domain/primitives";
import { MockWorkbenchApi } from "../../shared/api/mock-workbench-api";
import { BacktestDetailPage } from "./BacktestDetailPage";
import { BacktestListPage } from "./BacktestListPage";

function createRun(id = "00000000-0000-4000-8000-000000000701") {
  return backtestRunDetailSchema.parse({
    id,
    status: "completed",
    symbol: "BTCUSDT",
    timeframe: "1h",
    startAt: "2026-06-01T00:00:00Z",
    endAt: "2026-06-08T00:00:00Z",
    initialCash: "10000",
    strategyId: "sma-crossover",
    strategyVersion: "v1",
    riskConfig: {
      maxExposureFraction: "0.2",
      stopLossFraction: "0.02",
      dailyLossFraction: "0.03",
      maxDrawdownFraction: "0.15",
      cooldownCandles: 3,
      quantityIncrement: "0.0001",
    },
    executionConfig: {
      feeRate: "0.001",
      slippageRate: "0.0005",
      fillRatio: "1",
    },
    createdAt: "2026-06-08T00:01:00Z",
    finishedAt: "2026-06-08T00:01:05Z",
    summary: {
      initialCash: "10000",
      finalEquity: "10125.5",
      netPnl: "125.5",
      realizedPnl: "125.5",
      unrealizedPnl: "0",
      returnFraction: "0.01255",
      maxDrawdownFraction: "0.045",
      winRate: "0.6",
      profitFactor: "1.8",
      closedTradeCount: 1,
      fillCount: 2,
      rejectionCount: 0,
      openPositionQuantity: "0",
      candleCount: 168,
      snapshotHash:
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    },
    closedTrades: [
      {
        openedAt: "2026-06-02T00:00:00Z",
        closedAt: "2026-06-03T00:00:00Z",
        quantity: "0.01",
        netPnl: "125.5",
      },
    ],
    events: [
      {
        sequence: 1,
        kind: "decision",
        occurredAt: "2026-06-02T00:00:00Z",
        candleSequence: 24,
        idempotencyKey: "backtest-701-candle-24",
        payload: { signal: "buy" },
      },
      {
        sequence: 2,
        kind: "completed",
        occurredAt: "2026-06-08T00:01:05Z",
        candleSequence: null,
        idempotencyKey: null,
        payload: { status: "completed" },
      },
    ],
    failureCode: null,
    failureMessage: null,
  });
}

class RecordingBacktestApi extends MockWorkbenchApi {
  readonly requests: BacktestRequest[] = [];

  readonly run: BacktestRunDetail;

  constructor(id?: string) {
    super();
    this.run = createRun(id);
  }

  override listBacktests(): Promise<Page<BacktestRunSummary>> {
    return Promise.resolve({
      items: [this.run],
      page: 1,
      pageSize: 20,
      total: 1,
    });
  }

  override startBacktest(input: BacktestRequest): Promise<BacktestRunDetail> {
    this.requests.push(input);
    return Promise.resolve(this.run);
  }

  override getBacktest(backtestId: string): Promise<BacktestRunDetail> {
    return Promise.resolve({ ...this.run, id: backtestId });
  }
}

class FailingBacktestApi extends RecordingBacktestApi {
  override listBacktests(): Promise<Page<BacktestRunSummary>> {
    return Promise.reject(
      new Error("private backtest storage detail must stay hidden"),
    );
  }
}

function renderBacktests(api: RecordingBacktestApi = new RecordingBacktestApi()) {
  window.history.replaceState({}, "", "/backtests");
  render(
    <AppProviders api={api}>
      <Routes>
        <Route path="/backtests" element={<BacktestListPage />} />
        <Route
          path="/backtests/:backtestId"
          element={<BacktestDetailPage />}
        />
      </Routes>
    </AppProviders>,
  );
  return api;
}

describe("BacktestListPage", () => {
  it("submits a UTC range, then renders the persisted result summary", async () => {
    const user = userEvent.setup();
    const api = renderBacktests();

    await screen.findByRole("table", { name: "回测运行记录" });
    await user.clear(screen.getByLabelText("开始时间（UTC）"));
    await user.type(
      screen.getByLabelText("开始时间（UTC）"),
      "2026-06-01T00:00:00Z",
    );
    await user.click(screen.getByRole("button", { name: "运行历史回测" }));

    expect(await screen.findByText("最大回撤")).toBeVisible();
    expect(
      screen.getByText("历史模拟，不等同于模拟盘或实盘"),
    ).toBeVisible();
    expect(api.requests).toEqual([
      expect.objectContaining({
        symbol: "BTCUSDT",
        timeframe: "1h",
        startAt: "2026-06-01T00:00:00Z",
      }),
    ]);
  });

  it("renders an accessible record table and an encoded detail link", async () => {
    const api = renderBacktests(
      new RecordingBacktestApi("00000000-0000-4000-8000-000000000702"),
    );

    const table = await screen.findByRole("table", {
      name: "回测运行记录",
    });
    expect(
      within(table).getByRole("link", { name: "查看回测详情" }),
    ).toHaveAttribute(
      "href",
      `/backtests/${encodeURIComponent(api.run.id)}`,
    );
    expect(
      screen.queryByRole("button", { name: /下单|开仓|自动交易/ }),
    ).not.toBeInTheDocument();
  });

  it("renders a safe list error without exposing service details", async () => {
    renderBacktests(new FailingBacktestApi());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("无法读取回测记录，请稍后重试。");
    expect(alert).not.toHaveTextContent("private backtest storage detail");
  });
});
