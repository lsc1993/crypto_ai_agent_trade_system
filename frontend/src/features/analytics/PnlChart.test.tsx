import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { analyticsSnapshotSchema } from "../../domain/analytics";
import { PnlChart } from "./PnlChart";
import { toEquityChartSeries } from "./equity-chart-series";

function equityCurve() {
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
    tradeCalendar: [],
    generatedAt: "2025-01-15T12:05:00Z",
  }).equityCurve;
}

describe("PnlChart", () => {
  it("converts canonical decimal strings to numbers only in a one-way display adapter", () => {
    const source = equityCurve();

    expect(toEquityChartSeries(source)).toEqual([
      {
        at: "2025-01-10T00:00:00Z",
        equity: 4.2,
        netPnl: 4.2,
      },
      {
        at: "2025-01-11T00:00:00Z",
        equity: 9.4,
        netPnl: 9.4,
      },
    ]);
    expect(source[0]?.equity).toBe("4.20");
    expect(source[1]?.netPnl).toBe("9.40");
  });

  it("renders an accessible visual and complete text-table alternative", () => {
    render(<PnlChart points={equityCurve()} />);

    expect(
      screen.getByRole("img", { name: "权益曲线，共 2 个数据点" }),
    ).toBeVisible();
    const table = screen.getByRole("table", {
      name: "权益曲线文本数据",
    });
    expect(within(table).getByText("2025-01-10T00:00:00Z")).toBeVisible();
    expect(within(table).getAllByText("4.20")).toHaveLength(2);
    expect(within(table).getByText("2025-01-11T00:00:00Z")).toBeVisible();
    expect(within(table).getAllByText("9.40")).toHaveLength(2);
  });
});
