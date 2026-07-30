import { z } from "zod";

import {
  httpUrlSchema,
  identifierSchema,
  paginationSchema,
  symbolSchema,
  utcIsoStringSchema,
} from "./primitives";

export const reportStatusSchema = z.enum([
  "queued",
  "running",
  "completed",
  "degraded",
  "failed",
]);

export const analysisEvidenceSchema = z.object({
  id: identifierSchema,
  symbol: symbolSchema,
  source: z.string().trim().min(1),
  sourceUrl: httpUrlSchema,
  observedAt: utcIsoStringSchema,
  summary: z.string(),
});

export const analysisReportSummarySchema = z.object({
  id: identifierSchema,
  analysisId: identifierSchema,
  symbol: symbolSchema,
  status: reportStatusSchema,
  title: z.string().trim().min(1),
  summary: z.string(),
  createdAt: utcIsoStringSchema,
  dataCutoffAt: utcIsoStringSchema.nullable(),
});

export const analysisReportSchema = analysisReportSummarySchema.extend({
  facts: z.array(z.string()),
  inferences: z.array(z.string()),
  risks: z.array(z.string()),
  limitations: z.array(z.string()),
  evidence: z.array(analysisEvidenceSchema),
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
