import { describe, expect, it } from "vitest";

import { analysisReportSchema } from "./report";

const detailedText = "本次冻结证据仅描述可观察市场状态，不构成任何交易指令或账户操作。";

function dualReport(marketMetrics: object | null) {
  return {
    id: "report-btc-001",
    analysisId: "analysis-btc-001",
    symbol: "BTCUSDT",
    status: "completed",
    title: "BTCUSDT 冻结市场研究",
    summary: "本报告仅基于本次冻结公开证据。",
    facts: [],
    inferences: [],
    risks: [],
    limitations: [],
    createdAt: "2026-08-14T12:00:00Z",
    dataCutoffAt: "2026-08-14T12:00:00Z",
    generatedAt: "2026-08-14T12:00:00Z",
    generatorKind: "langgraph_deepseek",
    evidence: [
      {
        id: "evidence-btc-001",
        symbol: "BTCUSDT",
        source: "binance_usdm_public_rest",
        sourceUrl: "https://www.binance.com/en/futures/BTCUSDT",
        observedAt: "2026-08-14T12:00:00Z",
        summary: "冻结公开市场快照。",
      },
    ],
    agentAnalysis: {
      horizon: "dual_horizon",
      outlook: "neutral",
      confidence: "medium",
      trendAlignment: {},
      supportZones: [],
      resistanceZones: [],
      catalysts: [],
      risksAndInvalidation: [],
      dataQuality: {
        freshness: "fresh",
        missingInputs: [],
        sourceCoverage: "complete",
      },
      limitations: [],
      marketMetrics,
      narrative: {
        marketOverview: {
          headline: "冻结公开数据等待进一步确认",
          summary: detailedText.repeat(10),
          evidenceIds: ["evidence-btc-001"],
        },
        shortTerm: {
          horizon: "short_term",
          outlook: "neutral",
          heading: "短期结构等待进一步确认",
          thesis: detailedText.repeat(12),
          drivers: [
            {
              label: "冻结公开数据",
              detail: detailedText.repeat(7),
              evidenceIds: ["evidence-btc-001"],
            },
          ],
          invalidation: [
            {
              condition: "新的冻结市场数据出现显著变化。",
              impact: "短期观点需要重新评估。",
              evidenceIds: ["evidence-btc-001"],
            },
          ],
        },
        longTerm: {
          horizon: "long_term",
          outlook: "neutral",
          heading: "长期结构等待进一步确认",
          thesis: detailedText.repeat(12),
          drivers: [
            {
              label: "冻结公开数据",
              detail: detailedText.repeat(7),
              evidenceIds: ["evidence-btc-001"],
            },
          ],
          invalidation: [
            {
              condition: "新的冻结市场数据出现显著变化。",
              impact: "长期观点需要重新评估。",
              evidenceIds: ["evidence-btc-001"],
            },
          ],
        },
      },
    },
  };
}

const completeMetrics = {
  price: "68000.12",
  change24h: "-2.50",
  volume24h: "123456789.01",
  fundingRate: "0.0001",
  openInterest: "456789012.34",
  fearGreedValue: 23,
  fearGreedClassification: "Extreme Fear",
  fearGreedChange7d: -11,
};

describe("analysisReportSchema frozen market metrics", () => {
  it("accepts a complete typed market snapshot for a dual-horizon report", () => {
    const parsed = analysisReportSchema.parse(dualReport(completeMetrics));

    expect(parsed.agentAnalysis?.marketMetrics).toEqual(completeMetrics);
  });

  it("rejects a dual-horizon report without a frozen market snapshot", () => {
    expect(() => analysisReportSchema.parse(dualReport(null))).toThrow();
  });

  it("rejects a partial frozen sentiment group", () => {
    expect(() =>
      analysisReportSchema.parse(
        dualReport({ ...completeMetrics, fearGreedClassification: null }),
      ),
    ).toThrow("Fear and greed metrics");
  });
});
