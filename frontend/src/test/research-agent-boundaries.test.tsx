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
  generatedAt: "2026-08-10T12:00:01Z",
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
    narrative: null,
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

const detailedChineseText =
  "本次冻结证据显示价格、流动性与情绪信号仍需交叉验证，市场结论只描述可观察条件而不构成交易指令。";

const dualHorizonAgentReport = {
  ...agentReport,
  title: "BTCUSDT 流动性回暖但趋势尚未确认",
  summary: "本次冻结证据支持短期与长期市场观点的分层展示。",
  agentAnalysis: {
    ...agentReport.agentAnalysis,
    horizon: "dual_horizon",
    narrative: {
      marketOverview: {
        headline: "流动性回暖但趋势尚未确认",
        summary: detailedChineseText.repeat(8),
        evidenceIds: ["evidence-agent-001"],
      },
      shortTerm: {
        horizon: "short_term",
        outlook: "neutral",
        heading: "短期观察等待关键价位确认",
        thesis: detailedChineseText.repeat(10),
        drivers: [
          {
            label: "冻结市场快照",
            detail: detailedChineseText.repeat(5),
            evidenceIds: ["evidence-agent-001"],
          },
        ],
        invalidation: [
          {
            condition: "关键价位附近的收盘结构出现持续变化。",
            impact: "短期观点需要基于新的冻结证据重新评估。",
            evidenceIds: ["evidence-agent-001"],
          },
        ],
      },
      longTerm: {
        horizon: "long_term",
        outlook: "neutral",
        heading: "长期趋势仍取决于流动性条件",
        thesis: detailedChineseText.repeat(10),
        drivers: [
          {
            label: "公开新闻与情绪",
            detail: detailedChineseText.repeat(5),
            evidenceIds: ["evidence-agent-001"],
          },
        ],
        invalidation: [
          {
            condition: "宏观流动性与公开市场结构同步转弱。",
            impact: "长期观点需要基于新的冻结证据重新评估。",
            evidenceIds: ["evidence-agent-001"],
          },
        ],
      },
    },
  },
} as const;

describe("dual-horizon agent research report boundary", () => {
  it("accepts a detailed Chinese narrative with frozen evidence references", () => {
    const parsed = analysisReportSchema.parse(dualHorizonAgentReport);

    expect(parsed.agentAnalysis?.horizon).toBe("dual_horizon");
    expect(parsed.agentAnalysis?.narrative?.shortTerm.horizon).toBe(
      "short_term",
    );
  });

  it("rejects a nested narrative reference outside the current frozen evidence", () => {
    expect(() =>
      analysisReportSchema.parse({
        ...dualHorizonAgentReport,
        agentAnalysis: {
          ...dualHorizonAgentReport.agentAnalysis,
          narrative: {
            ...dualHorizonAgentReport.agentAnalysis.narrative,
            longTerm: {
              ...dualHorizonAgentReport.agentAnalysis.narrative.longTerm,
              drivers: [
                {
                  ...dualHorizonAgentReport.agentAnalysis.narrative.longTerm
                    .drivers[0],
                  evidenceIds: ["evidence-from-another-report"],
                },
              ],
            },
          },
        },
      }),
    ).toThrow();
  });
});
