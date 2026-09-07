import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { factorAnalysisSchema } from "../../domain/report-factors";
import { ReportFactorAnalysis } from "./ReportFactorAnalysis";

const at = "2026-09-06T12:00:00Z";
const base = {
  status: "partial", windowStart: null, windowEnd: at, observedAt: null,
  fetchedAt: at, facts: [], events: [], evidenceIds: [], interpretation: null, limitations: [],
};

function factors() {
  return factorAnalysisSchema.parse({
    policy: { ...base, evidenceIds: ["policy-1"], events: [{
      institution: "Federal Reserve", title: "FOMC statement", summary: "Policy statement.",
      publishedAt: "2026-09-01T12:00:00Z", evidenceId: "policy-1",
      sourceUrl: "https://www.federalreserve.gov/newsevents/pressreleases.htm",
    }], interpretation: {
      topic: "policy", outlook: "neutral", summary: "政策可能改变流动性预期。",
      shortTerm: "短期关注风险偏好。", longTerm: "长期取决于政策实施。",
      invalidation: "若政策撤回则重新评估。", evidenceIds: ["policy-1"],
    } },
    funding: { ...base, status: "failed", limitations: ["资金费率历史采集失败。"] },
    etf: { ...base, evidenceIds: ["etf-1"], facts: [
      { label: "最新交易日", value: "2026-09-04", unit: "text" },
      { label: "日度净流出", value: "-12500000", unit: "usd" },
      { label: "已披露零流量", value: "0", unit: "usd" },
      { label: "尚未披露的基金", value: null, unit: "usd" },
    ] },
  });
}

describe("report factor topics", () => {
  it("renders policy provenance and model interpretation with frozen citations", () => {
    render(<ReportFactorAnalysis analysis={factors()} />);
    const policy = screen.getByRole("region", { name: "近一周美国关键政策" });
    expect(within(policy).getByText("Federal Reserve")).toBeVisible();
    expect(within(policy).getByRole("link", { name: "FOMC statement" })).toHaveAttribute(
      "href", "https://www.federalreserve.gov/newsevents/pressreleases.htm",
    );
    expect(within(policy).getByText("政策可能改变流动性预期。")).toBeVisible();
    expect(within(policy).getAllByRole("link", { name: /查看证据/ })[0]).toHaveAttribute(
      "href", "#evidence-policy-1",
    );
  });

  it("distinguishes negative, zero, missing ETF flows and a failed funding source", () => {
    render(<ReportFactorAnalysis analysis={factors()} />);
    const etf = screen.getByRole("region", { name: "美国现货 ETF 资金流向" });
    expect(within(etf).getByText("-12,500,000 USD")).toBeVisible();
    expect(within(etf).getByText("0 USD")).toBeVisible();
    expect(within(etf).getByText("未披露／不可用")).toBeVisible();
    expect(within(etf).getByText("2026-09-04")).toBeVisible();
    expect(screen.getByText("资金费率历史采集失败。")).toBeVisible();
  });

  it("keeps historical reports without topics renderable", () => {
    const { container } = render(<ReportFactorAnalysis analysis={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("rejects model references from another topic", () => {
    const value = factors();
    value.policy.interpretation!.evidenceIds = ["etf-1"];
    expect(factorAnalysisSchema.safeParse(value).success).toBe(false);
  });
});
