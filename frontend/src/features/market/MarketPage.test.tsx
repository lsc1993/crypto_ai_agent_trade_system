import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";

import { AppProviders } from "../../app/providers";
import {
  marketDetailSchema,
  type MarketDetail,
} from "../../domain/market";
import type { Symbol, Timeframe } from "../../domain/primitives";
import { MockWorkbenchApi } from "../../shared/api/mock-workbench-api";
import { mockMarketDetails } from "../../shared/mocks/fixtures";
import { MarketPage } from "./MarketPage";

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

function renderMarket(api: MockWorkbenchApi = new RecordingMarketApi()) {
  window.history.replaceState({}, "", "/market/BTCUSDT");
  render(
    <AppProviders api={api}>
      <Routes>
        <Route path="/market/:symbol" element={<MarketPage />} />
      </Routes>
    </AppProviders>,
  );
}

describe("MarketPage", () => {
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
    const controls = [
      ...screen.getAllByRole("button"),
      ...screen.queryAllByRole("link"),
    ];
    for (const control of controls) {
      expect(control).not.toHaveAccessibleName(/下单|开仓|自动交易/);
    }
  });
});
