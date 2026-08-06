import { z } from "zod";

import {
  decimalStringSchema,
  nonNegativeDecimalStringSchema,
  paginationSchema,
  positiveDecimalStringSchema,
  utcIsoStringSchema,
  uuidSchema,
} from "./primitives";

const paperSymbolSchema = z.literal("BTCUSDT");
const paperStatusSchema = z.enum(["active", "archived"]);
const paperActionSchema = z.enum(["open_long", "close_long"]);
const intentSourceSchema = z.enum(["strategy", "manual", "risk"]);
const orderStatusSchema = z.enum(["pending", "filled", "partially_filled"]);

export const paperAccountCreateSchema = z.object({
  initialCash: positiveDecimalStringSchema,
});

export const manualPaperIntentSchema = z.object({
  clientRequestId: uuidSchema,
  action: paperActionSchema,
});

export const paperRiskConfigSchema = z.object({
  maxExposureFraction: nonNegativeDecimalStringSchema,
  stopLossFraction: nonNegativeDecimalStringSchema,
  dailyLossFraction: nonNegativeDecimalStringSchema,
  maxDrawdownFraction: nonNegativeDecimalStringSchema,
  cooldownCandles: z.number().int().nonnegative(),
  quantityIncrement: positiveDecimalStringSchema,
});

export const paperExecutionConfigSchema = z.object({
  feeRate: nonNegativeDecimalStringSchema,
  slippageRate: nonNegativeDecimalStringSchema,
  fillRatio: positiveDecimalStringSchema,
});

const paperAccountBaseSchema = z.object({
  id: uuidSchema,
  status: paperStatusSchema,
  symbol: paperSymbolSchema,
  initialCash: positiveDecimalStringSchema,
  cash: nonNegativeDecimalStringSchema,
  equity: nonNegativeDecimalStringSchema,
  peakEquity: nonNegativeDecimalStringSchema,
  dailyStartEquity: nonNegativeDecimalStringSchema,
  dailyRealizedLoss: nonNegativeDecimalStringSchema,
  dailyDay: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  cooldownRemaining: z.number().int().nonnegative(),
  lastClosedCandleAt: utcIsoStringSchema.nullable(),
  riskConfig: paperRiskConfigSchema,
  executionConfig: paperExecutionConfigSchema,
  createdAt: utcIsoStringSchema,
  archivedAt: utcIsoStringSchema.nullable(),
});

export const paperAccountSummarySchema = z.object({
  id: uuidSchema,
  status: paperStatusSchema,
  symbol: paperSymbolSchema,
  cash: nonNegativeDecimalStringSchema,
  equity: nonNegativeDecimalStringSchema,
  positionQuantity: nonNegativeDecimalStringSchema,
  createdAt: utcIsoStringSchema,
  archivedAt: utcIsoStringSchema.nullable(),
});

export const paperPositionSchema = z.object({
  quantity: nonNegativeDecimalStringSchema,
  averageEntryPrice: positiveDecimalStringSchema.nullable(),
  remainingEntryCost: nonNegativeDecimalStringSchema,
  openedAt: utcIsoStringSchema.nullable(),
  updatedAt: utcIsoStringSchema,
});

export const paperMarketSnapshotSchema = z.object({
  price: positiveDecimalStringSchema,
  source: z.string().trim().min(1),
  observedAt: utcIsoStringSchema,
  fetchedAt: utcIsoStringSchema,
  payloadHash: z.string().regex(/^[0-9a-f]{64}$/),
});

export const paperOrderSchema = z.object({
  action: paperActionSchema,
  idempotencyKey: z.string().trim().min(1),
  submittedAt: utcIsoStringSchema,
  requestedQuantity: positiveDecimalStringSchema,
  status: orderStatusSchema,
});

export const paperFillSchema = z.object({
  action: paperActionSchema,
  orderIdempotencyKey: z.string().trim().min(1),
  submittedAt: utcIsoStringSchema,
  filledAt: utcIsoStringSchema,
  requestedQuantity: positiveDecimalStringSchema,
  quantity: positiveDecimalStringSchema,
  price: positiveDecimalStringSchema,
  fee: nonNegativeDecimalStringSchema,
  status: z.enum(["filled", "partially_filled"]),
});

export const paperLedgerEntrySchema = z.object({
  occurredAt: utcIsoStringSchema,
  kind: paperActionSchema,
  cashDelta: decimalStringSchema,
  positionDelta: decimalStringSchema,
  realizedPnl: decimalStringSchema,
  fee: nonNegativeDecimalStringSchema,
  cashAfter: nonNegativeDecimalStringSchema,
  quantityAfter: nonNegativeDecimalStringSchema,
});

export const paperAuditEventSchema = z.object({
  sequence: z.number().int().nonnegative(),
  kind: z.enum([
    "intent",
    "no_signal",
    "market_unavailable",
    "risk_approved",
    "risk_rejected",
    "risk_exit",
    "order",
    "fill",
    "archived",
  ]),
  occurredAt: utcIsoStringSchema,
  idempotencyKey: z.string().nullable(),
  payload: z.record(z.string(), z.unknown()),
});

export const paperActionOutcomeSchema = z.object({
  kind: z.enum(["filled", "risk_rejected", "no_signal", "risk_exit"]),
  source: intentSourceSchema.nullable(),
  idempotencyKey: z.string().nullable(),
  reason: z.string().nullable(),
});

export const paperPerformancePointSchema = z.object({
  at: utcIsoStringSchema,
  cash: nonNegativeDecimalStringSchema,
  positionQuantity: nonNegativeDecimalStringSchema,
  equity: nonNegativeDecimalStringSchema,
  netPnl: decimalStringSchema,
});

export const paperDecisionStatsSchema = z.object({
  manualIntentCount: z.number().int().nonnegative(),
  strategyEvaluationCount: z.number().int().nonnegative(),
  noSignalCount: z.number().int().nonnegative(),
  riskRejectedCount: z.number().int().nonnegative(),
  riskExitCount: z.number().int().nonnegative(),
  orderCount: z.number().int().nonnegative(),
  fillCount: z.number().int().nonnegative(),
});

export const paperPerformanceSnapshotSchema = z.object({
  accountId: uuidSchema,
  initialCash: positiveDecimalStringSchema,
  currentEquity: nonNegativeDecimalStringSchema,
  netPnl: decimalStringSchema,
  returnFraction: decimalStringSchema,
  realizedPnl: decimalStringSchema,
  unrealizedPnl: decimalStringSchema,
  totalFee: nonNegativeDecimalStringSchema,
  maxDrawdownAmount: nonNegativeDecimalStringSchema,
  maxDrawdownFraction: nonNegativeDecimalStringSchema,
  openFillCount: z.number().int().nonnegative(),
  closeFillCount: z.number().int().nonnegative(),
  profitableCloseCount: z.number().int().nonnegative(),
  unprofitableCloseCount: z.number().int().nonnegative(),
  breakEvenCloseCount: z.number().int().nonnegative(),
  closeWinRate: nonNegativeDecimalStringSchema,
  decisionStats: paperDecisionStatsSchema,
  historyStatus: z.enum(["complete", "partial"]),
  historyStartedAt: utcIsoStringSchema,
  historyEndedAt: utcIsoStringSchema,
  equityCurve: z.array(paperPerformancePointSchema),
  generatedAt: utcIsoStringSchema,
});

export const paperAccountDetailSchema = paperAccountBaseSchema.extend({
  position: paperPositionSchema,
  latestSnapshot: paperMarketSnapshotSchema.nullable(),
  orders: z.array(paperOrderSchema),
  fills: z.array(paperFillSchema),
  ledgerEntries: z.array(paperLedgerEntrySchema),
  events: z.array(paperAuditEventSchema),
  actionOutcome: paperActionOutcomeSchema.nullable(),
});

export const paperAccountFiltersSchema = paginationSchema;

export type PaperAccountCreate = z.infer<typeof paperAccountCreateSchema>;
export type ManualPaperIntent = z.infer<typeof manualPaperIntentSchema>;
export type PaperAccountSummary = z.infer<typeof paperAccountSummarySchema>;
export type PaperAccountDetail = z.infer<typeof paperAccountDetailSchema>;
export type PaperAccountFilters = z.input<typeof paperAccountFiltersSchema>;
export type PaperPerformanceSnapshot = z.infer<
  typeof paperPerformanceSnapshotSchema
>;
export type PaperDecisionStats = z.infer<typeof paperDecisionStatsSchema>;
