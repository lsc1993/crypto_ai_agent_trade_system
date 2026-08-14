import Decimal from "decimal.js";
import { z } from "zod";

import {
  decimalStringSchema,
  nonNegativeDecimalStringSchema,
  positiveDecimalStringSchema,
  httpUrlSchema,
  identifierSchema,
  paginationSchema,
  symbolSchema,
  timeframeSchema,
  utcIsoStringSchema,
} from "./primitives";

export const reportStatusSchema = z.enum([
  "queued",
  "running",
  "completed",
  "degraded",
  "failed",
]);

export const analysisEvidenceSchema = z
  .object({
    id: identifierSchema,
    symbol: symbolSchema,
    source: z.string().trim().min(1),
    sourceUrl: httpUrlSchema,
    observedAt: utcIsoStringSchema,
    summary: z.string(),
  })
  .strict();

export const reportGeneratorKindSchema = z.enum([
  "deterministic",
  "langgraph_deepseek",
]);

const marketOutlookSchema = z.enum(["bullish", "bearish", "neutral"]);
const trendDirectionSchema = z.enum([
  "bullish",
  "bearish",
  "neutral",
  "unknown",
]);
const agentTextSchema = z.string().trim().min(1).max(1000);
const chineseAgentTextSchema = agentTextSchema.refine(
  (value) => /[\u3400-\u9fff]/.test(value),
  "Detailed research text must contain Chinese characters",
);
const evidenceIdsSchema = z
  .array(identifierSchema)
  .min(1)
  .max(12)
  .refine(
    (evidenceIds) => new Set(evidenceIds).size === evidenceIds.length,
    "Evidence references must not repeat",
  );

const priceZoneSchema = z
  .object({
    lower: positiveDecimalStringSchema,
    upper: positiveDecimalStringSchema,
    timeframe: timeframeSchema,
    rationale: agentTextSchema,
  })
  .strict()
  .refine((zone) => new Decimal(zone.upper).gte(zone.lower), {
    message: "Price zone upper bound must not be below its lower bound",
  });

const catalystSchema = z
  .object({
    category: z.string().trim().min(1).max(100),
    direction: marketOutlookSchema,
    claim: agentTextSchema,
    evidenceIds: evidenceIdsSchema,
    timing: agentTextSchema,
  })
  .strict();

const riskAndInvalidationSchema = z
  .object({
    condition: agentTextSchema,
    impact: agentTextSchema,
    evidenceIds: evidenceIdsSchema,
  })
  .strict();

const evidenceBackedClaimSchema = z
  .object({
    label: chineseAgentTextSchema,
    detail: chineseAgentTextSchema,
    evidenceIds: evidenceIdsSchema,
  })
  .strict();

const marketOverviewSchema = z
  .object({
    headline: chineseAgentTextSchema,
    summary: chineseAgentTextSchema,
    evidenceIds: evidenceIdsSchema,
  })
  .strict();

const researchPerspectiveSchema = z
  .object({
    horizon: z.enum(["short_term", "long_term"]),
    outlook: marketOutlookSchema,
    heading: chineseAgentTextSchema,
    thesis: chineseAgentTextSchema,
    drivers: z.array(evidenceBackedClaimSchema).min(1).max(4),
    invalidation: z.array(riskAndInvalidationSchema).min(1).max(4),
  })
  .strict();

const agentResearchNarrativeSchema = z
  .object({
    marketOverview: marketOverviewSchema,
    shortTerm: researchPerspectiveSchema,
    longTerm: researchPerspectiveSchema,
  })
  .strict()
  .superRefine((narrative, context) => {
    if (narrative.shortTerm.horizon !== "short_term") {
      context.addIssue({
        code: "custom",
        message: "The short-term perspective must use the short_term horizon",
        path: ["shortTerm", "horizon"],
      });
    }
    if (narrative.longTerm.horizon !== "long_term") {
      context.addIssue({
        code: "custom",
        message: "The long-term perspective must use the long_term horizon",
        path: ["longTerm", "horizon"],
      });
    }
    const displayLength = [
      narrative.marketOverview.headline,
      narrative.marketOverview.summary,
      narrative.shortTerm.thesis,
      narrative.longTerm.thesis,
      ...narrative.shortTerm.drivers.map((driver) => driver.detail),
      ...narrative.longTerm.drivers.map((driver) => driver.detail),
    ].join("").length;
    if (displayLength < 1500 || displayLength > 2500) {
      context.addIssue({
        code: "custom",
        message: "Detailed research narrative must contain 1,500 to 2,500 display characters",
      });
    }
  });

const marketMetricsSchema = z
  .object({
    price: positiveDecimalStringSchema,
    change24h: decimalStringSchema,
    volume24h: nonNegativeDecimalStringSchema,
    fundingRate: decimalStringSchema,
    openInterest: nonNegativeDecimalStringSchema,
    fearGreedValue: z.number().int().min(0).max(100).nullable(),
    fearGreedClassification: z.string().trim().min(1).max(100).nullable(),
    fearGreedChange7d: z.number().int().min(-100).max(100).nullable(),
  })
  .strict()
  .superRefine((metrics, context) => {
    const sentiment = [
      metrics.fearGreedValue,
      metrics.fearGreedClassification,
      metrics.fearGreedChange7d,
    ];
    if (
      sentiment.some((value) => value === null) &&
      sentiment.some((value) => value !== null)
    ) {
      context.addIssue({
        code: "custom",
        message: "Fear and greed metrics must be complete or unavailable",
      });
    }
  });

const agentAnalysisBaseSchema = z
  .object({
    outlook: marketOutlookSchema,
    confidence: z.enum(["low", "medium", "high"]),
    trendAlignment: z.partialRecord(timeframeSchema, trendDirectionSchema),
    supportZones: z.array(priceZoneSchema).max(12),
    resistanceZones: z.array(priceZoneSchema).max(12),
    catalysts: z.array(catalystSchema).max(12),
    risksAndInvalidation: z.array(riskAndInvalidationSchema).max(12),
    dataQuality: z
      .object({
        freshness: z.enum(["fresh", "stale", "missing", "failed"]),
        missingInputs: z.array(z.string().trim().min(1).max(100)).max(12),
        sourceCoverage: z.enum(["none", "partial", "complete"]),
      })
      .strict(),
    limitations: z.array(agentTextSchema).max(12),
  })
  .strict();

const agentAnalysisSchema = z.discriminatedUnion("horizon", [
  agentAnalysisBaseSchema.extend({
    horizon: z.literal("1_to_3_days"),
    narrative: z.null(),
    marketMetrics: z.null(),
  }),
  agentAnalysisBaseSchema.extend({
    horizon: z.literal("dual_horizon"),
    narrative: agentResearchNarrativeSchema,
    marketMetrics: marketMetricsSchema,
  }),
]);

export const analysisReportSummarySchema = z
  .object({
    id: identifierSchema,
    analysisId: identifierSchema,
    symbol: symbolSchema,
    status: reportStatusSchema,
    title: z.string().trim().min(1),
    summary: z.string(),
    createdAt: utcIsoStringSchema,
    dataCutoffAt: utcIsoStringSchema.nullable(),
    generatorKind: reportGeneratorKindSchema,
  })
  .strict();

export const analysisReportSchema = analysisReportSummarySchema
  .extend({
    facts: z.array(z.string()),
    inferences: z.array(z.string()),
    risks: z.array(z.string()),
    limitations: z.array(z.string()),
    generatedAt: utcIsoStringSchema,
    evidence: z.array(analysisEvidenceSchema),
    agentAnalysis: agentAnalysisSchema.nullable(),
  })
  .superRefine((report, context) => {
    const hasAgentAnalysis = report.agentAnalysis !== null;
    if (
      (report.generatorKind === "langgraph_deepseek") !==
      hasAgentAnalysis
    ) {
      context.addIssue({
        code: "custom",
        message: "Agent reports must contain validated Agent analysis only",
        path: ["agentAnalysis"],
      });
      return;
    }
    if (report.agentAnalysis === null) {
      return;
    }

    const evidenceIds = new Set(report.evidence.map((evidence) => evidence.id));
    const referenceGroups = [
      ...report.agentAnalysis.catalysts.map((item, index) => ({
        path: ["agentAnalysis", "catalysts", index, "evidenceIds"],
        evidenceIds: item.evidenceIds,
      })),
      ...report.agentAnalysis.risksAndInvalidation.map((item, index) => ({
        path: ["agentAnalysis", "risksAndInvalidation", index, "evidenceIds"],
        evidenceIds: item.evidenceIds,
      })),
      ...(report.agentAnalysis.narrative === null
        ? []
        : [
            {
              path: [
                "agentAnalysis",
                "narrative",
                "marketOverview",
                "evidenceIds",
              ],
              evidenceIds: report.agentAnalysis.narrative.marketOverview
                .evidenceIds,
            },
            ...report.agentAnalysis.narrative.shortTerm.drivers.map(
              (item, index) => ({
                path: [
                  "agentAnalysis",
                  "narrative",
                  "shortTerm",
                  "drivers",
                  index,
                  "evidenceIds",
                ],
                evidenceIds: item.evidenceIds,
              }),
            ),
            ...report.agentAnalysis.narrative.shortTerm.invalidation.map(
              (item, index) => ({
                path: [
                  "agentAnalysis",
                  "narrative",
                  "shortTerm",
                  "invalidation",
                  index,
                  "evidenceIds",
                ],
                evidenceIds: item.evidenceIds,
              }),
            ),
            ...report.agentAnalysis.narrative.longTerm.drivers.map(
              (item, index) => ({
                path: [
                  "agentAnalysis",
                  "narrative",
                  "longTerm",
                  "drivers",
                  index,
                  "evidenceIds",
                ],
                evidenceIds: item.evidenceIds,
              }),
            ),
            ...report.agentAnalysis.narrative.longTerm.invalidation.map(
              (item, index) => ({
                path: [
                  "agentAnalysis",
                  "narrative",
                  "longTerm",
                  "invalidation",
                  index,
                  "evidenceIds",
                ],
                evidenceIds: item.evidenceIds,
              }),
            ),
          ]),
    ];
    for (const group of referenceGroups) {
      for (const [index, evidenceId] of group.evidenceIds.entries()) {
        if (!evidenceIds.has(evidenceId)) {
          context.addIssue({
            code: "custom",
            message: "Agent references must belong to this report's evidence",
            path: [...group.path, index],
          });
        }
      }
    }
  });

export const analysisStreamEventSchema = z.object({
  analysisId: identifierSchema,
  symbol: symbolSchema,
  status: reportStatusSchema,
  occurredAt: utcIsoStringSchema,
  message: z.string(),
});

export const reportFiltersSchema = paginationSchema.extend({
  symbol: symbolSchema.optional(),
  status: reportStatusSchema.optional(),
});

export type ReportStatus = z.infer<typeof reportStatusSchema>;
export type AnalysisEvidence = z.infer<typeof analysisEvidenceSchema>;
export type AnalysisReportSummary = z.infer<
  typeof analysisReportSummarySchema
>;
export type AnalysisReport = z.infer<typeof analysisReportSchema>;
export type AnalysisStreamEvent = z.infer<typeof analysisStreamEventSchema>;
export type ReportFilters = z.input<typeof reportFiltersSchema>;

export function toAnalysisReportSummary(
  report: AnalysisReport,
): AnalysisReportSummary {
  return analysisReportSummarySchema.parse({
    id: report.id,
    analysisId: report.analysisId,
    symbol: report.symbol,
    status: report.status,
    title: report.title,
    summary: report.summary,
    createdAt: report.createdAt,
    dataCutoffAt: report.dataCutoffAt,
    generatorKind: report.generatorKind,
  });
}
