import { z } from "zod";

import {
  decimalStringSchema,
  symbolSchema,
  utcIsoStringSchema,
} from "./primitives";
import { tradeDirectionSchema, tradeHorizonSchema } from "./trade";

export const analyticsFiltersSchema = z
  .object({
    symbol: symbolSchema.optional(),
    direction: tradeDirectionSchema.optional(),
    horizon: tradeHorizonSchema.optional(),
    label: z.string().trim().min(1).optional(),
    from: utcIsoStringSchema.optional(),
    to: utcIsoStringSchema.optional(),
  })
  .refine(
    ({ from, to }) =>
      from === undefined || to === undefined || Date.parse(from) <= Date.parse(to),
    { message: "Analytics start must not be after end", path: ["from"] },
  );

export const equityPointSchema = z.object({
  at: utcIsoStringSchema,
  equity: decimalStringSchema,
  netPnl: decimalStringSchema,
});

export const tradeCalendarPointSchema = z.object({
  at: utcIsoStringSchema,
  netPnl: decimalStringSchema,
  tradeCount: z.number().int().nonnegative(),
});

export const analyticsSnapshotSchema = z.object({
  netPnl: decimalStringSchema,
  winRate: decimalStringSchema,
  profitFactor: decimalStringSchema,
  expectancy: decimalStringSchema,
  maxDrawdown: decimalStringSchema,
  equityCurve: z.array(equityPointSchema),
  tradeCalendar: z.array(tradeCalendarPointSchema),
  generatedAt: utcIsoStringSchema,
});

export type AnalyticsFilters = z.input<typeof analyticsFiltersSchema>;
export type EquityPoint = z.infer<typeof equityPointSchema>;
export type TradeCalendarPoint = z.infer<typeof tradeCalendarPointSchema>;
export type AnalyticsSnapshot = z.infer<typeof analyticsSnapshotSchema>;
