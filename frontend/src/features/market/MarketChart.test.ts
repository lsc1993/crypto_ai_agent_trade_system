import { describe, expect, it } from "vitest";

import { mockMarketDetails } from "../../shared/mocks/fixtures";
import { toChartSeries } from "./MarketChart";

describe("toChartSeries", () => {
  it("converts canonical decimal strings one way for chart display without mutating domain data", () => {
    const source = mockMarketDetails[0]?.series[0];
    if (source === undefined) {
      throw new Error("BTCUSDT chart fixture is missing");
    }
    const original = structuredClone(source);

    const chartSeries = toChartSeries(source);

    expect(chartSeries[0]).toMatchObject({
      time: 1736935200,
      open: 67000,
      high: 68000,
      low: 66800,
      close: 67600,
    });
    expect(typeof chartSeries[0]?.open).toBe("number");
    expect(typeof chartSeries[0]?.close).toBe("number");
    expect(source).toEqual(original);
    expect(typeof source.candles[0]?.open).toBe("string");
    expect(typeof source.candles[0]?.close).toBe("string");
  });
});
