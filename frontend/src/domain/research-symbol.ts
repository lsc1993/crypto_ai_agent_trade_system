import { z } from "zod";

import { symbolSchema, utcIsoStringSchema } from "./primitives";

const capabilityNameSchema = z.enum([
  "market",
  "candles",
  "derivatives",
  "funding",
  "news",
  "sentiment",
  "etf",
]);

export const researchCapabilitySchema = z
  .object({
    name: capabilityNameSchema,
    status: z.enum(["supported", "unsupported", "unverified"]),
    message: z.string().trim().min(1),
  })
  .strict();

export const researchSymbolEntrySchema = z
  .object({
    symbol: symbolSchema,
    baseAsset: z.string().trim().min(1),
    quoteAsset: z.literal("USDT"),
    marginAsset: z.literal("USDT"),
    contractType: z.literal("PERPETUAL"),
    enabled: z.boolean(),
    keywords: z.array(z.string()).default([]),
    capabilities: z.array(researchCapabilitySchema).default([]),
    version: z.number().int().positive(),
    createdAt: utcIsoStringSchema,
    archivedAt: utcIsoStringSchema.nullable(),
    canResearch: z.boolean(),
    lastSync: z
      .object({
        id: z.string(),
        status: z.enum([
          "queued",
          "running",
          "ready",
          "partial",
          "failed",
          "cancelled",
        ]),
      })
      .passthrough()
      .nullable(),
  })
  .strict();

export const researchSymbolListSchema = z
  .object({ items: z.array(researchSymbolEntrySchema) })
  .strict();

export type ResearchSymbolEntry = z.infer<typeof researchSymbolEntrySchema>;
