import Decimal from "decimal.js";
import { z } from "zod";

import { httpUrlSchema, identifierSchema, utcIsoStringSchema } from "./primitives";

const ids = z.array(identifierSchema).max(12).refine(
  (values) => new Set(values).size === values.length,
  "Topic evidence references must not repeat",
);
const text = z.string().trim().min(1).max(1000);
const interpretationSchema = z.object({
  topic: z.enum(["policy", "funding", "etf"]),
  outlook: z.enum(["bullish", "bearish", "neutral"]),
  summary: text, shortTerm: text, longTerm: text, invalidation: text,
  evidenceIds: ids.refine((values) => values.length > 0),
}).strict();

const factSchema = z.object({
  label: z.string().min(1).max(160),
  value: z.string().max(1000).nullable(),
  unit: z.enum(["text", "rate", "usd", "count"]),
}).strict().superRefine((fact, context) => {
  if (fact.value === null || fact.unit === "text") return;
  try {
    if (new Decimal(fact.value).isFinite()) return;
  } catch { /* Invalid numerical strings must not reach the formatter. */ }
  context.addIssue({ code: "custom", path: ["value"], message: "Invalid numeric fact" });
});

const topicSchema = z.object({
  status: z.enum(["available", "partial", "missing", "failed"]),
  windowStart: utcIsoStringSchema.nullable(),
  windowEnd: utcIsoStringSchema,
  observedAt: utcIsoStringSchema.nullable(),
  fetchedAt: utcIsoStringSchema.nullable(),
  facts: z.array(factSchema).max(30),
  events: z.array(z.object({
    institution: z.string(), title: z.string().max(4000), summary: z.string().max(4000),
    publishedAt: utcIsoStringSchema, evidenceId: identifierSchema, sourceUrl: httpUrlSchema,
  }).strict()).max(12),
  evidenceIds: ids,
  interpretation: interpretationSchema.nullable(),
  limitations: z.array(z.string()).max(12),
}).strict().superRefine((topic, context) => {
  const known = new Set(topic.evidenceIds);
  if (topic.interpretation !== null && (
    topic.status === "missing" || topic.status === "failed" ||
    topic.interpretation.evidenceIds.some((id) => !known.has(id))
  )) context.addIssue({ code: "custom", message: "Interpretation requires this topic's evidence" });
  if (topic.events.some((event) => !known.has(event.evidenceId))) {
    context.addIssue({ code: "custom", message: "Policy events require topic evidence" });
  }
});

export const factorAnalysisSchema = z.object({
  policy: topicSchema, funding: topicSchema, etf: topicSchema,
}).strict().superRefine((analysis, context) => {
  for (const kind of ["policy", "funding", "etf"] as const) {
    const interpretation = analysis[kind].interpretation;
    if (interpretation !== null && interpretation.topic !== kind) {
      context.addIssue({ code: "custom", path: [kind], message: "Topic mismatch" });
    }
  }
});

export type FactorAnalysis = z.infer<typeof factorAnalysisSchema>;
export type FactorTopic = z.infer<typeof topicSchema>;
export type FactorFact = z.infer<typeof factSchema>;
