import Decimal from "decimal.js";
import { z } from "zod";

import {
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
const evidenceIdsSchema = z.array(identifierSchema).min(1).max(12);

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

const agentAnalysisSchema = z
  .object({
    horizon: z.literal("1_to_3_days"),
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
