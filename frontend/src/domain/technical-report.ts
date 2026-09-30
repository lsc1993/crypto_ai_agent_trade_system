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

export const technicalReportSchema = z.object({
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

export const technicalReportFiltersSchema = paginationSchema.extend({
  symbol: symbolSchema.optional(),
});
export const technicalReportPageSchema = pageSchema(technicalReportSchema);

export type TechnicalReport = z.infer<typeof technicalReportSchema>;
export type TechnicalReportFilters = z.infer<typeof technicalReportFiltersSchema>;
