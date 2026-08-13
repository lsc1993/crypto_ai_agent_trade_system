import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockMarketDetails } from "../../shared/mocks/fixtures";
import { MarketChart } from "./MarketChart";

const chartHarness = vi.hoisted(() => {
  const setData = vi.fn();
  const fitContent = vi.fn();
  const remove = vi.fn();
  const addSeries = vi.fn(() => ({ setData }));
  const createChart = vi.fn(() => ({
    addSeries,
    remove,
    timeScale: () => ({ fitContent }),
  }));

  return {
    addSeries,
    createChart,
    fitContent,
    remove,
    setData,
  };
});

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: "candlestick-series",
  ColorType: { Solid: "solid" },
  createChart: chartHarness.createChart,
}));

function marketSeries() {
  const series = mockMarketDetails[0]?.series[0];
  if (series === undefined) {
    throw new Error("BTCUSDT chart fixture is missing");
  }
  return series;
}

describe("MarketChart", () => {
  let disconnect: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    disconnect = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe = vi.fn();
        disconnect = disconnect;
      },
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders crypto-colored candlesticks and releases the chart on unmount", () => {
    const { unmount } = render(
      <MarketChart series={marketSeries()} timeframe="1h" />,
    );

    const chartContainer = screen.getByRole("img", {
      name: "1h K 线图，共 2 个数据点",
    });
    expect(chartHarness.createChart).toHaveBeenCalledWith(
      chartContainer,
      expect.any(Object),
    );
    expect(chartHarness.addSeries).toHaveBeenCalledWith(
      "candlestick-series",
      {
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderUpColor: "#22c55e",
        borderDownColor: "#ef4444",
        wickUpColor: "#22c55e",
        wickDownColor: "#ef4444",
      },
    );
    expect(chartHarness.setData).toHaveBeenCalledWith([
      {
        time: 1736935200,
        open: 67000,
        high: 68000,
        low: 66800,
        close: 67600,
      },
      {
        time: 1736938800,
        open: 67600,
        high: 68100,
        low: 67400,
        close: 67890.12,
      },
    ]);
    expect(chartHarness.fitContent).toHaveBeenCalledOnce();

    unmount();

    expect(disconnect).toHaveBeenCalledOnce();
    expect(chartHarness.remove).toHaveBeenCalledOnce();
  });
});
