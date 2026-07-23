import {
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppProviders } from "../../app/providers";
import type { Page } from "../../domain/primitives";
import {
  tradeFiltersSchema,
  type Trade,
  type TradeFilters,
} from "../../domain/trade";
import { MockWorkbenchApi } from "../../shared/api/mock-workbench-api";
import { mockTrades } from "../../shared/mocks/fixtures";
import { TradeListPage } from "./TradeListPage";

class RecordingTradeListApi extends MockWorkbenchApi {
  readonly filters: TradeFilters[] = [];

  override listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    const parsed = tradeFiltersSchema.parse(filters);
    this.filters.push(parsed);
    return Promise.resolve({
      items: mockTrades,
      page: parsed.page,
      pageSize: parsed.pageSize,
      total: mockTrades.length,
    });
  }
}

class PendingTradeListApi extends RecordingTradeListApi {
  override listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    this.filters.push(tradeFiltersSchema.parse(filters));
    return new Promise(() => undefined);
  }
}

class FailingTradeListApi extends RecordingTradeListApi {
  override listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    this.filters.push(tradeFiltersSchema.parse(filters));
    return Promise.reject(
      new Error("private trade list service detail must stay hidden"),
    );
  }
}

class EmptyTradeListApi extends RecordingTradeListApi {
  override listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    const parsed = tradeFiltersSchema.parse(filters);
    this.filters.push(parsed);
    return Promise.resolve({
      items: [],
      page: parsed.page,
      pageSize: parsed.pageSize,
      total: 0,
    });
  }
}

function renderTradeList(
  api: MockWorkbenchApi = new RecordingTradeListApi(),
  search = "",
  nextSearch?: string,
) {
  window.history.replaceState({}, "", `/trades${search}`);
  render(
    <AppProviders api={api}>
      <Routes>
        <Route
          path="/trades"
          element={
            nextSearch === undefined ? (
              <TradeListPage />
            ) : (
              <>
                <QueryNavigationButton search={nextSearch} />
                <TradeListPage />
              </>
            )
          }
        />
      </Routes>
    </AppProviders>,
  );
}

function QueryNavigationButton({ search }: { search: string }) {
  const navigate = useNavigate();

  return (
    <button
      type="button"
      onClick={() => {
        void navigate(`/trades${search}`);
      }}
    >
      切换交易日志筛选链接
    </button>
  );
}

describe("TradeListPage", () => {
  it("renders the standard loading state while journal data is pending", () => {
    renderTradeList(new PendingTradeListApi());

    expect(screen.getByText("正在加载数据")).toBeVisible();
    expect(screen.getByRole("status")).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("renders a safe Chinese error without exposing API details", async () => {
    renderTradeList(new FailingTradeListApi());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("无法读取交易日志，请稍后重试。");
    expect(alert).not.toHaveTextContent("private trade list service");
  });

  it("renders an explicit empty state", async () => {
    renderTradeList(new EmptyTradeListApi());

    expect(await screen.findByText("暂无数据")).toBeVisible();
    expect(screen.getByText("当前筛选条件下没有交易日志。")).toBeVisible();
  });

  it("parses known query filters and ignores unknown parameters", async () => {
    const api = new RecordingTradeListApi();
    renderTradeList(
      api,
      "?symbol=BTCUSDT&direction=long&horizon=short_term&status=closed" +
        "&label=%E5%A4%8D%E7%9B%98%E6%A0%B7%E4%BE%8B" +
        "&from=2025-01-01T00%3A00%3A00Z" +
        "&to=2025-01-31T23%3A59%3A59Z&page=2&pageSize=10" +
        "&apiKey=MUST_NOT_REACH_API&reportBody=MUST_NOT_RENDER",
    );

    await waitFor(() => {
      expect(api.filters).toEqual([
        {
          symbol: "BTCUSDT",
          direction: "long",
          horizon: "short_term",
          status: "closed",
          label: "复盘样例",
          from: "2025-01-01T00:00:00Z",
          to: "2025-01-31T23:59:59Z",
          page: 2,
          pageSize: 10,
        },
      ]);
    });
    expect(screen.queryByText("MUST_NOT_RENDER")).not.toBeInTheDocument();
  });

  it("rejects invalid known query values before calling the API", async () => {
    const api = new RecordingTradeListApi();
    renderTradeList(
      api,
      "?direction=sideways&from=2025-01-01T08%3A00%3A00%2B08%3A00",
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "交易日志筛选条件无效，请检查后重试。",
    );
    expect(api.filters).toEqual([]);
  });

  it("synchronizes the request and visible filters when the journal URL changes", async () => {
    const user = userEvent.setup();
    const api = new RecordingTradeListApi();
    renderTradeList(
      api,
      "?symbol=BTCUSDT&direction=long&page=1&pageSize=20",
      "?symbol=ETHUSDT&direction=short&page=2&pageSize=10",
    );

    await waitFor(() => {
      expect(api.filters.at(-1)).toEqual({
        symbol: "BTCUSDT",
        direction: "long",
        page: 1,
        pageSize: 20,
      });
    });

    await user.click(
      screen.getByRole("button", { name: "切换交易日志筛选链接" }),
    );

    await waitFor(() => {
      expect(api.filters.at(-1)).toEqual({
        symbol: "ETHUSDT",
        direction: "short",
        page: 2,
        pageSize: 10,
      });
    });
    expect(screen.getByLabelText("标的")).toHaveValue("ETHUSDT");
    expect(screen.getByLabelText("方向")).toHaveValue("short");
  });

  it("submits parsed accessible filters and renders a Chinese journal table", async () => {
    const user = userEvent.setup();
    const api = new RecordingTradeListApi();
    renderTradeList(api);
    await screen.findByRole("heading", { name: "交易日志" });

    await user.selectOptions(screen.getByLabelText("标的"), "ETHUSDT");
    await user.selectOptions(screen.getByLabelText("方向"), "short");
    await user.selectOptions(
      screen.getByLabelText("持有周期"),
      "medium_term",
    );
    await user.selectOptions(screen.getByLabelText("状态"), "open");
    await user.type(screen.getByLabelText("标签"), "复盘");
    await user.type(
      screen.getByLabelText("开始时间（UTC）"),
      "2025-02-01T00:00:00Z",
    );
    await user.type(
      screen.getByLabelText("结束时间（UTC）"),
      "2025-02-28T23:59:59Z",
    );
    await user.click(
      screen.getByRole("button", { name: "应用筛选" }),
    );

    await waitFor(() => {
      expect(api.filters.at(-1)).toEqual({
        symbol: "ETHUSDT",
        direction: "short",
        horizon: "medium_term",
        status: "open",
        label: "复盘",
        from: "2025-02-01T00:00:00Z",
        to: "2025-02-28T23:59:59Z",
        page: 1,
        pageSize: 20,
      });
    });
    const table = screen.getByRole("table", { name: "交易日志记录" });
    expect(within(table).getByText("标的")).toBeVisible();
    expect(within(table).getByText("方向")).toBeVisible();
    expect(within(table).getByText("净盈亏")).toBeVisible();
    expect(within(table).getByText("关联报告 ID")).toBeVisible();
    expect(within(table).getByText("交易腿数")).toBeVisible();
    expect(within(table).getByText("report-btc-001")).toBeVisible();
    expect(within(table).getByText("2")).toBeVisible();
    expect(
      screen.getByRole("link", { name: "新增交易日志" }),
    ).toHaveAttribute("href", "/trades/new");
    expect(screen.queryByText("TRADE HISTORY")).not.toBeInTheDocument();

    const controls = [
      ...screen.getAllByRole("button"),
      ...screen.getAllByRole("link"),
    ];
    for (const control of controls) {
      expect(control).not.toHaveAccessibleName(
        /下单|开仓|自动交易|执行交易/,
      );
    }
  });
});
