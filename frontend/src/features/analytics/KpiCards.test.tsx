import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { analyticsSnapshotSchema } from "../../domain/analytics";
import { KpiCards } from "./KpiCards";

describe("KpiCards", () => {
  it("renders backend decimal metrics without using leverage to amplify PnL", () => {
    const snapshot = analyticsSnapshotSchema.parse({
      netPnl: "9.40",
      winRate: "0.625",
      profitFactor: "1.75",
      expectancy: "2.35",
      maxDrawdown: "-4.00",
      equityCurve: [],
      tradeCalendar: [],
      generatedAt: "2025-01-15T12:05:00Z",
    });

    render(<KpiCards snapshot={snapshot} />);

    expect(screen.getByText("净盈亏")).toBeVisible();
    expect(screen.getByText("9.40")).toBeVisible();
    expect(screen.getByText("胜率")).toBeVisible();
    expect(screen.getByText("0.625")).toBeVisible();
    expect(screen.getByText("利润因子")).toBeVisible();
    expect(screen.getByText("1.75")).toBeVisible();
    expect(screen.getByText("期望值")).toBeVisible();
    expect(screen.getByText("2.35")).toBeVisible();
    expect(screen.getByText("最大回撤")).toBeVisible();
    expect(screen.getByText("-4.00")).toBeVisible();
    expect(screen.getByText("生成时间（UTC）")).toBeVisible();
    expect(screen.getByText("2025-01-15T12:05:00Z")).toBeVisible();
    expect(screen.queryByText("18.80")).not.toBeInTheDocument();
  });
});
