import { z } from "zod";

import {
  decimalStringSchema,
  nonNegativeDecimalStringSchema,
  paginationSchema,
  positiveDecimalStringSchema,
  utcIsoStringSchema,
  uuidSchema,
} from "./primitives";

const backtestSymbolSchema = z.literal("BTCUSDT");
const backtestTimeframeSchema = z.literal("1h");

export const backtestRequestSchema = z
  .object({
    symbol: backtestSymbolSchema,
    timeframe: backtestTimeframeSchema,
    startAt: utcIsoStringSchema,
    endAt: utcIsoStringSchema,
    initialCash: positiveDecimalStringSchema,
  })
  .refine(({ startAt, endAt }) => Date.parse(startAt) < Date.parse(endAt), {
    message: "Backtest start must be before end",
    path: ["startAt"],
  });

export const backtestRiskConfigSchema = z.object({
  maxExposureFraction: decimalStringSchema,
  stopLossFraction: decimalStringSchema,
  dailyLossFraction: decimalStringSchema,
  maxDrawdownFraction: decimalStringSchema,
  cooldownCandles: z.number().int().nonnegative(),
  quantityIncrement: positiveDecimalStringSchema,
});

export const backtestExecutionConfigSchema = z.object({
  feeRate: nonNegativeDecimalStringSchema,
  slippageRate: nonNegativeDecimalStringSchema,
  fillRatio: positiveDecimalStringSchema,
});

export const backtestSummarySchema = z.object({
  initialCash: positiveDecimalStringSchema,
  finalEquity: decimalStringSchema,
  netPnl: decimalStringSchema,
  realizedPnl: decimalStringSchema,
  unrealizedPnl: decimalStringSchema,
  returnFraction: decimalStringSchema,
  maxDrawdownFraction: nonNegativeDecimalStringSchema,
  winRate: nonNegativeDecimalStringSchema,
  profitFactor: decimalStringSchema.nullable(),
  closedTradeCount: z.number().int().nonnegative(),
  fillCount: z.number().int().nonnegative(),
  rejectionCount: z.number().int().nonnegative(),
  openPositionQuantity: nonNegativeDecimalStringSchema,
  candleCount: z.number().int().positive(),
  snapshotHash: z.string().regex(/^[0-9a-f]{64}$/),
});

export const backtestClosedTradeSchema = z.object({
  openedAt: utcIsoStringSchema,
  closedAt: utcIsoStringSchema,
  quantity: positiveDecimalStringSchema,
  netPnl: decimalStringSchema,
});

export const backtestAuditEventSchema = z.object({
  sequence: z.number().int().nonnegative(),
  kind: z.enum([
    "decision",
    "risk_approved",
    "risk_rejected",
    "order",
    "fill",
    "risk_exit",
    "circuit_breaker",
    "completed",
  ]),
  occurredAt: utcIsoStringSchema,
  candleSequence: z.number().int().nonnegative().nullable(),
  idempotencyKey: z.string().nullable(),
  payload: z.record(z.string(), z.unknown()),
});

const backtestRunBaseSchema = z.object({
  id: uuidSchema,
  status: z.enum(["pending", "completed", "failed"]),
  symbol: backtestSymbolSchema,
  timeframe: backtestTimeframeSchema,
  startAt: utcIsoStringSchema,
  endAt: utcIsoStringSchema,
  initialCash: positiveDecimalStringSchema,
  strategyId: z.string().trim().min(1),
  strategyVersion: z.string().trim().min(1),
  riskConfig: backtestRiskConfigSchema,
  executionConfig: backtestExecutionConfigSchema,
  createdAt: utcIsoStringSchema,
  finishedAt: utcIsoStringSchema.nullable(),
  summary: backtestSummarySchema.nullable(),
  failureCode: z.string().nullable(),
  failureMessage: z.string().nullable(),
});

export const backtestRunSummarySchema = backtestRunBaseSchema;

export const backtestRunDetailSchema = backtestRunBaseSchema.extend({
  closedTrades: z.array(backtestClosedTradeSchema),
  events: z.array(backtestAuditEventSchema),
});

export const backtestFiltersSchema = paginationSchema;

export type BacktestRequest = z.infer<typeof backtestRequestSchema>;
export type BacktestRiskConfig = z.infer<typeof backtestRiskConfigSchema>;
export type BacktestExecutionConfig = z.infer<typeof backtestExecutionConfigSchema>;
export type BacktestSummary = z.infer<typeof backtestSummarySchema>;
export type BacktestClosedTrade = z.infer<typeof backtestClosedTradeSchema>;
export type BacktestAuditEvent = z.infer<typeof backtestAuditEventSchema>;
export type BacktestRunSummary = z.infer<typeof backtestRunSummarySchema>;
export type BacktestRunDetail = z.infer<typeof backtestRunDetailSchema>;
export type BacktestFilters = z.input<typeof backtestFiltersSchema>;
