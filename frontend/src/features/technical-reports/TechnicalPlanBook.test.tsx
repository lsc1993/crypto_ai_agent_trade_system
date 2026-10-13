import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { technicalReportV1Schema, technicalReportV2Schema } from "../../domain/technical-report";
import { technicalReportWire } from "../../test/technical-report-fixture";
import { TechnicalPlanBook } from "./TechnicalPlanBook";

const base = technicalReportV1Schema.omit({narrative: true}).strip().parse(technicalReportWire);
const claim = {
  text: "facts.trendAlignment.1h：bullish；facts.resistanceLevels.12：72000.12345678；noPlanReasons.0：trend_conflict；facts.volumeSignal：high；facts.smallBody：False；facts.breakout：none；latestClosedPrices.4h：70000；plans.0.state：awaiting_confirmation；volume_price。",
  evidenceId: base.analysis.evidenceId,
  factRefs: ["facts.trendAlignment.1h", "facts.resistanceLevels.12", "noPlanReasons.0", "facts.volumeSignal", "facts.smallBody", "facts.breakout", "latestClosedPrices.4h", "plans.0.state"],
  methodRefs: ["volume_price"],
};
const report = technicalReportV2Schema.parse({
  ...base, version: "technical-v2",
  context: { analysis: base.analysis, summaryPrice: "70000", latestClosedPrices: {"4h": "70000"}, dataCutoffAt: base.dataCutoffAt },
  decision: null,
  planBook: { stance: "wait", selectedPlanRef: null, marketStructure: [claim], supportingEvidence: [claim], counterEvidence: [claim], methodApplications: [claim], entryConditions: [], stopRationale: [], targetRationale: [], invalidation: [], alternative: [], waitingConditions: [claim], risks: [claim] },
  generation: { source: "model", quality: "complete", promptVersion: "technical-plan-1", diagnostics: [] },
});

describe("technical plan reading view", () => {
  it("does not describe three neutral periods as directional consensus", () => {
    const neutralReport = technicalReportV2Schema.parse({
      ...report,
      analysis: {...report.analysis, facts: {...report.analysis.facts, trendAlignment: {"1d": "neutral", "4h": "neutral", "1h": "neutral"}}},
    });
    render(<TechnicalPlanBook report={neutralReport} />);
    const structure = screen.getByRole("region", {name: "市场结构与周期判断"});
    expect(structure).toHaveTextContent("多周期均为中性，未形成方向共识");
    expect(structure).not.toHaveTextContent("多周期方向一致");
  });
  it("localizes saved claims and references without changing precise prices or the stored report", async () => {
    const before = JSON.stringify(report);
    render(<TechnicalPlanBook report={report} />);
    const waiting = screen.getByRole("region", {name: "等待与重新评估"});
    expect(waiting).toHaveTextContent("1小时趋势：上行");
    expect(waiting).toHaveTextContent("结构阻力位：72000.12345678");
    expect(waiting).toHaveTextContent("等待原因：日线、4 小时与 1 小时方向不一致；");
    expect(waiting).toHaveTextContent("成交量状态：放量");
    expect(waiting).toHaveTextContent("小实体：未识别");
    expect(waiting).toHaveTextContent("收盘突破方向：未确认突破");
    expect(waiting).toHaveTextContent("4小时最新收盘价：70000");
    expect(waiting).toHaveTextContent("冻结信号状态：等待后续确认");
    expect(waiting).toHaveTextContent("量价分析");
    const user = userEvent.setup();
    await user.click(within(waiting).getByText("查看依据"));
    expect(within(waiting).getByText(/结构阻力位（第13项）/)).toBeInTheDocument();
    await user.click(within(waiting).getByText("原始引用与证据标识"));
    expect(within(waiting).getByText(/facts.resistanceLevels.12/)).toBeInTheDocument();
    expect(JSON.stringify(report)).toBe(before);
  });

  it("puts the period comparison before expandable full market analysis and keeps risks visible", async () => {
    render(<TechnicalPlanBook report={report} />);
    const structure = screen.getByRole("region", {name: "市场结构与周期判断"});
    const table = within(structure).getByRole("table", {name: "多周期趋势对照"});
    expect(within(table).getByRole("row", {name: /日线.*上行.*69,000.*67,000/})).toBeInTheDocument();
    const details = within(structure).getByText("展开完整市场分析").closest("details");
    expect(details).not.toHaveAttribute("open");
    await userEvent.setup().click(within(structure).getByText("展开完整市场分析"));
    expect(details).toHaveAttribute("open");
    expect(screen.getByRole("region", {name: "风险与适用限制"})).toHaveTextContent("72000.12345678");
  });
});
