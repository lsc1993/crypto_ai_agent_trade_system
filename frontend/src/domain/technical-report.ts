import { z } from "zod";

import {
  nonNegativeDecimalStringSchema,
  pageSchema,
  paginationSchema,
  positiveDecimalStringSchema,
  symbolSchema,
  utcIsoStringSchema,
  uuidSchema,
} from "./primitives";

const technicalDirectionSchema = z.enum(["long", "short", "none"]);
const claimSchema = z.object({
  text: z.string().trim().min(1).max(500),
  evidenceIds: z.array(uuidSchema),
}).strict();

export const technicalReportV1Schema = z.object({
  version: z.literal("technical-v1"),
  id: uuidSchema,
  analysisId: uuidSchema,
  symbol: symbolSchema,
  status: z.enum(["completed", "degraded"]),
  createdAt: utcIsoStringSchema,
  dataCutoffAt: utcIsoStringSchema,
  analysis: z.object({
    quality: z.object({
      status: z.enum(["valid", "invalid"]),
      reasons: z.array(z.string()),
      candleCounts: z.record(z.string(), z.number().int().nonnegative()),
      latestClosedAt: z.record(z.string(), utcIsoStringSchema),
    }).strict(),
    facts: z.object({
      trendAlignment: z.record(z.string(), z.enum(["bullish", "bearish", "neutral"])),
      sma20: z.record(z.string(), positiveDecimalStringSchema),
      sma50: z.record(z.string(), positiveDecimalStringSchema),
      atr14: nonNegativeDecimalStringSchema,
      rangeHigh: positiveDecimalStringSchema,
      rangeLow: positiveDecimalStringSchema,
      volumeRatio: nonNegativeDecimalStringSchema,
      volumeSignal: z.enum(["high", "low", "ordinary"]),
      smallBody: z.boolean(),
      longUpperWick: z.boolean(),
      longLowerWick: z.boolean(),
      breakout: technicalDirectionSchema,
      supportLevels: z.array(positiveDecimalStringSchema),
      resistanceLevels: z.array(positiveDecimalStringSchema),
    }).strict().nullable(),
    plans: z.array(z.object({
      direction: z.enum(["long", "short"]),
      state: z.enum(["triggered", "awaiting_confirmation"]),
      triggerLevel: positiveDecimalStringSchema,
      entryLower: positiveDecimalStringSchema,
      entryUpper: positiveDecimalStringSchema,
      stopLoss: positiveDecimalStringSchema,
      target: positiveDecimalStringSchema,
      rewardRisk: nonNegativeDecimalStringSchema,
      feeRatePerSide: nonNegativeDecimalStringSchema,
      slippageRatePerSide: nonNegativeDecimalStringSchema,
      validUntil: utcIsoStringSchema,
      rationale: z.enum([
        "closed_volume_breakout_with_structural_target",
        "awaiting_closed_volume_breakout_with_structural_target",
      ]),
    }).strict()),
    noPlanReasons: z.array(z.string()),
    methods: z.array(z.object({
      id: z.string().min(1),
      version: z.string().min(1),
      sourceSkillId: z.string().min(1),
      sourceSha256: z.string().min(1),
      adaptedSha256: z.string().min(1),
      adaptationNote: z.string().min(1),
    }).strict()),
    evidenceId: uuidSchema,
  }).strict(),
  narrative: z.object({
    thesis: claimSchema,
    alternative: claimSchema,
    risks: z.array(claimSchema),
  }).strict().nullable(),
  errorCode: z.enum([
    "market_unavailable", "data_quality_insufficient", "model_not_configured",
    "model_timeout", "model_upstream_error", "model_invalid_response",
  ]).nullable(),
}).strict();

const planClaimSchema = z.object({
  text: z.string().min(1).max(5000), evidenceId: uuidSchema,
  factRefs: z.array(z.string().min(1)), methodRefs: z.array(z.string().min(1)),
}).strict();
const planBookSchema = z.object({
  stance: z.enum(["long", "short", "wait"]), selectedPlanRef: z.literal("plans.0").nullable(),
  marketStructure: z.array(planClaimSchema), supportingEvidence: z.array(planClaimSchema),
  counterEvidence: z.array(planClaimSchema), methodApplications: z.array(planClaimSchema),
  entryConditions: z.array(planClaimSchema), stopRationale: z.array(planClaimSchema),
  targetRationale: z.array(planClaimSchema), invalidation: z.array(planClaimSchema),
  alternative: z.array(planClaimSchema), waitingConditions: z.array(planClaimSchema), risks: z.array(planClaimSchema),
}).strict();
export const technicalReportV2Schema = technicalReportV1Schema.omit({narrative: true}).extend({
  version: z.literal("technical-v2"),
  context: z.object({analysis: technicalReportV1Schema.shape.analysis, summaryPrice: positiveDecimalStringSchema.nullable(), latestClosedPrices: z.record(z.string(), positiveDecimalStringSchema), dataCutoffAt: utcIsoStringSchema}).strict(),
  decision: planBookSchema.nullable(), planBook: planBookSchema,
  generation: z.object({source: z.enum(["model", "rules"]), quality: z.enum(["complete", "composition_fallback", "analysis_unavailable", "data_insufficient"]), promptVersion: z.literal("technical-plan-1"), diagnostics: z.array(z.object({
    stage: z.enum(["analysis", "composition"]), attempt: z.number().int().min(1).max(2),
    outcome: z.enum(["success", "length", "empty", "invalid", "timeout", "upstream", "not_configured"]),
    finishReason: z.enum(["stop", "length"]).nullable(), reasoningTokens: z.number().int().nonnegative().nullable(),
    completionTokens: z.number().int().nonnegative().nullable(), durationMs: z.number().int().nonnegative(),
    model: z.enum(["deepseek-v4-pro", "deepseek-v4-flash"]), thinking: z.boolean(),
    reasoningEffort: z.enum(["high", "low"]).nullable(), maxTokens: z.number().int().positive().max(65536),
  }).strict()).max(4)}).strict(),
  errorCode: z.enum(["market_unavailable", "data_quality_insufficient", "model_not_configured", "model_timeout", "model_upstream_error", "model_invalid_response", "model_output_limit", "model_empty_response", "run_timeout"]).nullable(),
}).strict();

export const technicalReportSchema = z.discriminatedUnion("version", [technicalReportV1Schema, technicalReportV2Schema]);
export const technicalRunSchema = z.object({
  id: uuidSchema, analysisId: uuidSchema, symbol: symbolSchema,
  status: z.enum(["queued", "running", "completed", "degraded", "failed"]),
  phase: z.enum(["queued", "collecting", "analyzing", "validating", "composing", "saving", "finished"]),
  createdAt: utcIsoStringSchema, updatedAt: utcIsoStringSchema, startedAt: utcIsoStringSchema.nullable(),
  finishedAt: utcIsoStringSchema.nullable(), reportId: uuidSchema.nullable(),
  errorCode: z.enum(["interrupted", "symbol_not_admitted", "run_timeout", "storage_unavailable", "research_failed"]).nullable(),
}).strict();
export type TechnicalRun = z.infer<typeof technicalRunSchema>;
export type TechnicalPlanReport = z.infer<typeof technicalReportV2Schema>;

export const technicalReportFiltersSchema = paginationSchema.extend({
  symbol: symbolSchema.optional(),
});
export const technicalReportPageSchema = pageSchema(technicalReportSchema);

export type TechnicalReport = z.infer<typeof technicalReportSchema>;
export type TechnicalReportFilters = z.infer<typeof technicalReportFiltersSchema>;
