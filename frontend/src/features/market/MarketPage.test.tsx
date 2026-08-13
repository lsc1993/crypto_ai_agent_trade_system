import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { Route, Routes, useLocation } from "react-router-dom";

import { AppProviders } from "../../app/providers";
import {
  marketDetailSchema,
  type MarketDetail,
} from "../../domain/market";
import type { Symbol, Timeframe } from "../../domain/primitives";
import { MockWorkbenchApi } from "../../shared/api/mock-workbench-api";
import { WorkbenchHttpError } from "../../shared/api/http-transport";
import { mockMarketDetails } from "../../shared/mocks/fixtures";
import { MarketPage } from "./MarketPage";

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

const requiredTimeframes: Timeframe[] = ["15m", "1h", "4h", "1d"];

function btcMarketDetail(): MarketDetail {
  const detail = mockMarketDetails.find(
    (candidate) => candidate.summary.symbol === "BTCUSDT",
  );
  if (detail === undefined) {
    throw new Error("BTCUSDT market fixture is missing");
  }
  return detail;
}

class RecordingMarketApi extends MockWorkbenchApi {
  readonly marketInputs: Array<{
    symbol: Symbol;
    timeframes: Timeframe[];
  }> = [];

  readonly startedSymbols: Symbol[] = [];

  override getMarket(input: {
    symbol: Symbol;
    timeframes: Timeframe[];
  }): Promise<MarketDetail> {
    this.marketInputs.push({
      symbol: input.symbol,
      timeframes: [...input.timeframes],
    });
    return super.getMarket(input);
  }

  override startReport(input: {
    symbol: Symbol;
  }): Promise<{ analysisId: string }> {
    this.startedSymbols.push(input.symbol);
    return super.startReport(input);
  }
}

class UntrustedNewsMarketApi extends RecordingMarketApi {
  override getMarket(input: {
    symbol: Symbol;
    timeframes: Timeframe[];
  }): Promise<MarketDetail> {
    this.marketInputs.push({
      symbol: input.symbol,
      timeframes: [...input.timeframes],
    });
    return Promise.resolve(
      marketDetailSchema.parse({
        ...btcMarketDetail(),
        news: [
          {
            id: "news-untrusted-markup",
            title: '<img src=x onerror="window.__task4Pwned=true">',
            summary: "<strong>这段摘要必须保持纯文本</strong>",
            source: "Untrusted Research Feed",
            sourceUrl: "https://example.com/untrusted-research",
            publishedAt: "2025-01-14T09:00:00Z",
            fetchedAt: "2025-01-14T09:05:00Z",
            symbols: ["BTCUSDT"],
          },
        ],
      }),
    );
  }
}

class EmptySectionsMarketApi extends RecordingMarketApi {
  override getMarket(input: {
    symbol: Symbol;
    timeframes: Timeframe[];
  }): Promise<MarketDetail> {
    this.marketInputs.push({
      symbol: input.symbol,
      timeframes: [...input.timeframes],
    });
    return Promise.resolve(
      marketDetailSchema.parse({
        ...btcMarketDetail(),
        series: [],
        news: [],
      }),
    );
  }
}

class MultiTimeframeMarketApi extends RecordingMarketApi {
  override getMarket(input: {
    symbol: Symbol;
    timeframes: Timeframe[];
  }): Promise<MarketDetail> {
    this.marketInputs.push({
      symbol: input.symbol,
      timeframes: [...input.timeframes],
    });
    const detail = btcMarketDetail();
    const oneHourSeries = detail.series.find(
      (series) => series.timeframe === "1h",
    );
    if (oneHourSeries === undefined) {
      throw new Error("BTCUSDT 1h market fixture is missing");
    }
    return Promise.resolve(
      marketDetailSchema.parse({
        ...detail,
        series: [
          ...detail.series,
          {
            timeframe: "4h",
            candles: oneHourSeries.candles.map((candle) => ({
              ...candle,
              timeframe: "4h",
            })),
          },
        ],
      }),
    );
  }
}

class PublicNoNewsMarketApi extends RecordingMarketApi {
  override getMarket(input: {
    symbol: Symbol;
    timeframes: Timeframe[];
  }): Promise<MarketDetail> {
    this.marketInputs.push({
      symbol: input.symbol,
      timeframes: [...input.timeframes],
    });
    const detail = btcMarketDetail();
    return Promise.resolve(
      marketDetailSchema.parse({
        ...detail,
        news: [],
        summary: {
          ...detail.summary,
          freshness: {
            status: "fresh",
            source: "binance_usdm_public_rest",
            observedAt: "2026-07-28T12:00:00Z",
            fetchedAt: "2026-07-28T12:00:01Z",
          },
        },
      }),
    );
  }
}

class UnavailablePublicMarketApi extends MockWorkbenchApi {
  override getMarket(): Promise<MarketDetail> {
    return Promise.reject(
      new WorkbenchHttpError(
        503,
        "market_data_unavailable",
        "公开行情服务不可用",
      ),
    );
  }
}

class PendingMarketApi extends MockWorkbenchApi {
  override getMarket(): Promise<MarketDetail> {
    return new Promise(() => undefined);
  }
}

class FailingMarketApi extends MockWorkbenchApi {
  override getMarket(): Promise<MarketDetail> {
    return Promise.reject(
      new Error("private market service detail must not reach the user"),
    );
  }
}

class PendingReportApi extends RecordingMarketApi {
  override startReport(input: {
    symbol: Symbol;
  }): Promise<{ analysisId: string }> {
    this.startedSymbols.push(input.symbol);
    return new Promise(() => undefined);
  }
}

class FailingReportApi extends RecordingMarketApi {
  override startReport(input: {
    symbol: Symbol;
  }): Promise<{ analysisId: string }> {
    this.startedSymbols.push(input.symbol);
    return Promise.reject(
      new Error("private report service detail must not reach the user"),
    );
  }
}

class RealReportMarketApi extends RecordingMarketApi {
  override startReport(input: {
    symbol: Symbol;
  }): Promise<{ analysisId: string; reportId: string }> {
    this.startedSymbols.push(input.symbol);
    return Promise.resolve({
      analysisId: "analysis-real-001",
      reportId: "report/segment?fragment",
    });
  }
}

function LocationProbe() {
  const location = useLocation();
  return <output aria-label="当前页面路径">{location.pathname}</output>;
}

function renderMarket(api: MockWorkbenchApi = new RecordingMarketApi()) {
  window.history.replaceState({}, "", "/market/BTCUSDT");
  render(
    <AppProviders api={api}>
      <Routes>
        <Route path="/market/:symbol" element={<MarketPage />} />
        <Route path="/reports/:reportId" element={<LocationProbe />} />
      </Routes>
    </AppProviders>,
  );
}

describe("MarketPage", () => {
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

  it("renders the standard loading state while market data is pending", () => {
    renderMarket(new PendingMarketApi());

    expect(screen.getByText("正在加载数据")).toBeVisible();
    expect(screen.getByRole("status")).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("renders a safe standard error state when market loading fails", async () => {
    renderMarket(new FailingMarketApi());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("数据加载失败");
    expect(alert).toHaveTextContent("无法读取市场研究数据，请稍后重试。");
    expect(alert).not.toHaveTextContent("private market service detail");
  });

  it("retains valid summary and research actions when chart and news sections are empty", async () => {
    renderMarket(new EmptySectionsMarketApi());

    const overview = await screen.findByRole("region", {
      name: "市场概览",
    });
    expect(within(overview).getByText("67,890.12")).toBeVisible();
    expect(within(overview).getByText("+1.25%")).toBeVisible();
    expect(
      within(overview).getByText("3,250,000,000.50"),
    ).toBeVisible();
    expect(
      screen.getByRole("region", { name: "衍生品指标" }),
    ).toHaveTextContent("数据正常");
    expect(
      screen.getByRole("button", { name: "生成 AI 研究报告" }),
    ).toBeEnabled();
    expect(
      screen.getByText("当前周期暂无 K 线数据，请选择其他周期。"),
    ).toBeVisible();
    expect(
      screen.getByText("当前标的暂无可追溯资讯。"),
    ).toBeVisible();
    expect(
      screen.queryByText("当前标的暂无市场研究数据。"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/查看 .* K 线文本数据/)).not.toBeInTheDocument();
  });

  it("labels the public provider and explains that no news source is enabled", async () => {
    renderMarket(new PublicNoNewsMarketApi());

    expect(
      await screen.findByText("来源：binance_usdm_public_rest"),
    ).toBeVisible();
    expect(
      screen.getByText("Binance 公开行情模式尚未配置新闻源。"),
    ).toBeVisible();
  });

  it("renders an explicit public-data error instead of a generic Mock fallback", async () => {
    renderMarket(new UnavailablePublicMarketApi());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("公开行情暂不可用");
    expect(alert).not.toHaveTextContent("公开行情服务不可用");
  });

  it("requests and renders exactly the four fixed research timeframes", async () => {
    const user = userEvent.setup();
    const api = new RecordingMarketApi();
    renderMarket(api);

    const tabs = await screen.findByRole("tablist", {
      name: "K 线周期",
    });
    for (const timeframe of requiredTimeframes) {
      expect(
        within(tabs).getByRole("tab", { name: timeframe }),
      ).toBeVisible();
    }
    expect(within(tabs).getAllByRole("tab")).toHaveLength(4);
    await waitFor(() => {
      expect(api.marketInputs).toEqual([
        {
          symbol: "BTCUSDT",
          timeframes: requiredTimeframes,
        },
      ]);
    });

    await user.click(within(tabs).getByRole("tab", { name: "4h" }));

    expect(
      within(tabs).getByRole("tab", { name: "4h" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      within(tabs).getByRole("tab", { name: "4h" }),
    ).toHaveAttribute("aria-controls", "market-timeframe-panel");

    await user.keyboard("{ArrowRight}");

    expect(
      within(tabs).getByRole("tab", { name: "1d" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      within(tabs).getByRole("tab", { name: "1d" }),
    ).toHaveFocus();
    expect(
      within(tabs).getByRole("tab", { name: "1d" }),
    ).toHaveAttribute("tabindex", "0");
    expect(
      within(tabs).getByRole("tab", { name: "4h" }),
    ).toHaveAttribute("tabindex", "-1");

    await user.keyboard("{Home}");

    expect(
      within(tabs).getByRole("tab", { name: "15m" }),
    ).toHaveFocus();
    expect(
      within(tabs).getByRole("tab", { name: "15m" }),
    ).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{End}");

    expect(
      within(tabs).getByRole("tab", { name: "1d" }),
    ).toHaveFocus();
    expect(
      within(tabs).getByRole("tab", { name: "1d" }),
    ).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{ArrowLeft}");

    expect(
      within(tabs).getByRole("tab", { name: "4h" }),
    ).toHaveFocus();
    const panel = screen.getByRole("tabpanel", { name: "4h" });
    expect(panel).toHaveAttribute("tabindex", "0");
  });

  it("renders formatted derivative metrics with explicit freshness metadata", async () => {
    renderMarket();

    const panel = await screen.findByRole("region", {
      name: "衍生品指标",
    });
    expect(within(panel).getByText("资金费率")).toBeVisible();
    expect(within(panel).getByText("+0.0100%")).toBeVisible();
    expect(within(panel).getByText("未平仓量")).toBeVisible();
    expect(within(panel).getByText("1,280,000,000")).toBeVisible();
    expect(
      within(panel).getByRole("status", {
        name: "数据新鲜度：数据正常",
      }),
    ).toBeVisible();
    expect(
      within(panel).getByText("来源：Deterministic Mock"),
    ).toBeVisible();
    expect(
      within(panel).getByText("2025-01-15T12:00:00Z"),
    ).toBeVisible();
    expect(
      within(panel).getByText("2025-01-15T12:00:05Z"),
    ).toBeVisible();
    expect(
      screen.getByRole("img", {
        name: "1h K 线图，共 2 个数据点",
      }),
    ).toBeVisible();
    expect(
      screen.getByRole("table", { name: "1h K 线文本数据" }),
    ).toBeInTheDocument();
  });

  it("keeps OHLC text data collapsed by default and synchronizes it with the selected timeframe", async () => {
    const user = userEvent.setup();
    renderMarket(new MultiTimeframeMarketApi());

    const summary = await screen.findByText("查看 1h K 线文本数据");
    const details = summary.closest("details");
    if (details === null) {
      throw new Error("K 线文本数据必须使用原生 details 折叠区");
    }
    expect(details).not.toHaveAttribute("open");
    expect(within(details).getByRole("table", { name: "1h K 线文本数据" })).toBeInTheDocument();
    const newsPanel = screen.getByRole("region", { name: "市场资讯" });
    expect(
      newsPanel.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);

    await user.click(summary);
    expect(details).toHaveAttribute("open");

    await user.click(screen.getByRole("tab", { name: "4h" }));
    expect(await screen.findByText("查看 4h K 线文本数据")).toBeVisible();
    expect(screen.getByRole("table", { name: "4h K 线文本数据" })).toBeInTheDocument();
  });

  it("renders untrusted news as plain text and secures its source link", async () => {
    const api = new UntrustedNewsMarketApi();
    renderMarket(api);

    const sourceLink = await screen.findByRole("link", {
      name: "Untrusted Research Feed",
    });
    const entry = sourceLink.closest("article");
    if (entry === null) {
      throw new Error("News source link must belong to a timeline article");
    }

    expect(
      within(entry).getByText(
        '<img src=x onerror="window.__task4Pwned=true">',
      ),
    ).toBeVisible();
    expect(
      within(entry).getByText(
        "<strong>这段摘要必须保持纯文本</strong>",
      ),
    ).toBeVisible();
    expect(entry.querySelector("img")).toBeNull();
    expect(entry.querySelector("strong")).toBeNull();
    expect(sourceLink).toHaveAttribute(
      "href",
      "https://example.com/untrusted-research",
    );
    expect(sourceLink).toHaveAttribute("target", "_blank");
    expect(sourceLink).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
    expect(within(entry).getByText("2025-01-14T09:00:00Z")).toBeVisible();
    expect(within(entry).getByText("2025-01-14T09:05:00Z")).toBeVisible();
  });

  it("starts manual AI research for the routed symbol without trading controls", async () => {
    const user = userEvent.setup();
    const api = new RecordingMarketApi();
    renderMarket(api);

    const generateButton = await screen.findByRole("button", {
      name: "生成 AI 研究报告",
    });
    await user.click(generateButton);

    await waitFor(() => {
      expect(api.startedSymbols).toEqual(["BTCUSDT"]);
    });
    expect(
      await screen.findByText(/研究任务已创建：analysis-new-/),
    ).toBeVisible();
    const controls = [
      ...screen.getAllByRole("button"),
      ...screen.queryAllByRole("link"),
    ];
    for (const control of controls) {
      expect(control).not.toHaveAccessibleName(/下单|开仓|自动交易/);
    }
  });

  it("opens the encoded immutable report detail after a real report is created", async () => {
    const user = userEvent.setup();
    const api = new RealReportMarketApi();
    renderMarket(api);

    await user.click(
      await screen.findByRole("button", {
        name: "生成 AI 研究报告",
      }),
    );

    expect(await screen.findByLabelText("当前页面路径")).toHaveTextContent(
      "/reports/report%2Fsegment%3Ffragment",
    );
    expect(api.startedSymbols).toEqual(["BTCUSDT"]);
  });

  it("keeps the research action pending while startReport is unresolved", async () => {
    const user = userEvent.setup();
    const api = new PendingReportApi();
    renderMarket(api);

    const generateButton = await screen.findByRole("button", {
      name: "生成 AI 研究报告",
    });
    await user.click(generateButton);

    expect(generateButton).toBeDisabled();
    expect(
      screen.getByText("正在创建研究任务，请稍候。"),
    ).toHaveAttribute("role", "status");
    expect(api.startedSymbols).toEqual(["BTCUSDT"]);
  });

  it("renders a safe research error when startReport fails", async () => {
    const user = userEvent.setup();
    const api = new FailingReportApi();
    renderMarket(api);

    await user.click(
      await screen.findByRole("button", {
        name: "生成 AI 研究报告",
      }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("研究任务创建失败，请稍后重试。");
    expect(alert).not.toHaveTextContent("private report service detail");
    expect(api.startedSymbols).toEqual(["BTCUSDT"]);
  });
});
