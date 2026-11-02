import { z } from "zod";

import { symbolSchema, utcIsoStringSchema, uuidSchema } from "./primitives";

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

const syncStatusSchema = z.enum([
  "queued", "running", "ready", "partial", "failed", "cancelled",
]);

const syncSourceCoverageSchema = z.object({
  name: capabilityNameSchema,
  status: z.enum(["available", "partial", "missing", "failed", "unsupported"]),
});

// 目录仅保留展示所需诊断字段，剥离 stage、来源正文和载荷；离线样例允许缺项。
const syncDiagnosticsSchema = z.object({
  id: z.string(),
  status: syncStatusSchema,
  createdAt: utcIsoStringSchema.optional(),
  startedAt: utcIsoStringSchema.nullable().optional(),
  completedAt: utcIsoStringSchema.nullable().optional(),
  sources: z.array(syncSourceCoverageSchema).optional(),
  error: z.string().nullable().optional(),
});

// 重试响应使用后端完整任务契约；目录中的离线样例保留精简 lastSync。
export const researchSymbolSyncRunSchema = z.object({
  id: uuidSchema,
  symbol: symbolSchema,
  version: z.number().int().positive(),
  status: syncStatusSchema,
  stage: z.string(),
  createdAt: utcIsoStringSchema,
  startedAt: utcIsoStringSchema.nullable(),
  completedAt: utcIsoStringSchema.nullable(),
  leaseToken: uuidSchema.nullable(),
  leaseUntil: utcIsoStringSchema.nullable(),
  snapshotId: uuidSchema.nullable(),
  sources: z.array(z.object({
    name: capabilityNameSchema,
    status: syncSourceCoverageSchema.shape.status,
    message: z.string(),
    payload: z.record(z.string(), z.unknown()),
    payloadSha256: z.string().regex(/^[a-f0-9]{64}$/),
  }).strict()),
  error: z.string().nullable(),
}).strict();

export type ResearchSymbolSyncRun = z.infer<typeof researchSymbolSyncRunSchema>;

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
    lastSync: syncDiagnosticsSchema.nullable(),
  })
  .strict();

export const researchSymbolListSchema = z
  .object({ items: z.array(researchSymbolEntrySchema) })
  .strict();

export type ResearchSymbolEntry = z.infer<typeof researchSymbolEntrySchema>;
