import { describe, expect, it } from "vitest";

import { analysisReportSchema } from "../domain/report";

const agentReport = {
  id: "report-agent-001",
  analysisId: "analysis-agent-001",
  symbol: "BTCUSDT",
  status: "completed",
  title: "BTCUSDT research",
  summary: "Frozen public evidence research.",
  createdAt: "2026-08-10T12:00:00Z",
  dataCutoffAt: "2026-08-10T12:00:00Z",
  generatorKind: "langgraph_deepseek",
  facts: [],
  inferences: [],
  risks: [],
  limitations: ["Not trading advice."],
  evidence: [
    {
      id: "evidence-agent-001",
      symbol: "BTCUSDT",
      source: "CoinDesk",
      sourceUrl: "https://www.coindesk.com/example",
      observedAt: "2026-08-10T12:00:00Z",
      summary: "Public English evidence.",
    },
  ],
  agentAnalysis: {
    horizon: "1_to_3_days",
    outlook: "neutral",
    confidence: "medium",
    trendAlignment: { "1h": "neutral" },
    supportZones: [],
    resistanceZones: [],
    catalysts: [
      {
        category: "market",
        direction: "neutral",
        claim: "Public evidence is mixed.",
        evidenceIds: ["evidence-agent-001"],
        timing: "Within one to three days.",
      },
    ],
    risksAndInvalidation: [],
    dataQuality: {
      freshness: "fresh",
      missingInputs: [],
      sourceCoverage: "partial",
    },
    limitations: ["Not trading advice."],
  },
} as const;

describe("agent research report boundary", () => {
  it("retains only the bounded Agent report contract", () => {
    const parsed = analysisReportSchema.parse(agentReport);

    expect(parsed.generatorKind).toBe("langgraph_deepseek");
    expect(parsed.agentAnalysis?.horizon).toBe("1_to_3_days");
  });

  it("rejects catalyst references outside the current frozen evidence", () => {
    expect(() =>
      analysisReportSchema.parse({
        ...agentReport,
        agentAnalysis: {
          ...agentReport.agentAnalysis,
          catalysts: [
            {
              ...agentReport.agentAnalysis.catalysts[0],
              evidenceIds: ["evidence-from-another-report"],
            },
          ],
        },
      }),
    ).toThrow();
  });

  it("rejects a reversed high-precision price zone without number coercion", () => {
    expect(() =>
      analysisReportSchema.parse({
        ...agentReport,
        agentAnalysis: {
          ...agentReport.agentAnalysis,
          supportZones: [
            {
              lower: "99999999999999999999999999999999999999",
              upper: "99999999999999999999999999999999999998",
              timeframe: "1h",
              rationale: "Invalid reversed zone.",
            },
          ],
        },
      }),
    ).toThrow();
  });

  it("rejects unexpected report fields instead of silently accepting model data", () => {
    expect(() =>
      analysisReportSchema.parse({
        ...agentReport,
        rawModelResponse: "must never cross the browser boundary",
      }),
    ).toThrow();
  });
});
