import Decimal from "decimal.js";
import { z } from "zod";

import {
  decimalStringSchema,
  identifierSchema,
  nonNegativeDecimalStringSchema,
  paginationSchema,
  positiveDecimalStringSchema,
  symbolSchema,
  utcIsoStringSchema,
  uuidSchema,
} from "./primitives";

export const tradeDirectionSchema = z.enum(["long", "short"]);
export const tradeHorizonSchema = z.enum(["short_term", "medium_term"]);
export const tradeLegActionSchema = z.enum(["open", "reduce", "close"]);
export const tradeStatusSchema = z.enum(["open", "closed"]);

export const tradeLegSchema = z.object({
  id: uuidSchema,
  action: tradeLegActionSchema,
  executedAt: utcIsoStringSchema,
  price: positiveDecimalStringSchema,
  quantity: positiveDecimalStringSchema,
  fee: nonNegativeDecimalStringSchema,
});

export const tradeCashflowSchema = z.object({
  id: uuidSchema,
  occurredAt: utcIsoStringSchema,
  amount: decimalStringSchema,
  reason: z.string().trim().min(1).max(500),
});

const tradeDraftBaseSchema = z.object({
  symbol: symbolSchema,
  direction: tradeDirectionSchema,
  horizon: tradeHorizonSchema,
  labels: z.array(z.string().trim().min(1)),
  linkedReportId: identifierSchema.nullable(),
  leverage: positiveDecimalStringSchema,
  legs: z.array(tradeLegSchema).min(1),
  fundingCashflows: z.array(tradeCashflowSchema),
  thesis: z.string(),
  review: z.string(),
});

function validateTradeLegAccounting(
  legs: z.infer<typeof tradeLegSchema>[],
  context: z.RefinementCtx,
): void {
    const identifiers = new Set<string>();
    let remaining = new Decimal(0);
    let closed = false;

    for (const [index, leg] of legs.entries()) {
      if (identifiers.has(leg.id)) {
        context.addIssue({
          code: "custom",
          path: ["legs", index, "id"],
          message: "Trade leg IDs must be unique",
        });
      }
      identifiers.add(leg.id);

      const quantity = new Decimal(leg.quantity);
      if (closed) {
        context.addIssue({
          code: "custom",
          path: ["legs", index],
          message: "No trade leg may follow a close action",
        });
        continue;
      }

      if (leg.action === "open") {
        remaining = remaining.plus(quantity);
        continue;
      }

      if (remaining.isZero() || quantity.greaterThan(remaining)) {
        context.addIssue({
          code: "custom",
          path: ["legs", index, "quantity"],
          message: "Reduction or close cannot exceed opened quantity",
        });
        continue;
      }

      if (leg.action === "reduce") {
        if (quantity.equals(remaining)) {
          context.addIssue({
            code: "custom",
            path: ["legs", index, "quantity"],
            message: "A reduce action must leave quantity open",
          });
        } else {
          remaining = remaining.minus(quantity);
        }
        continue;
      }

      if (!quantity.equals(remaining)) {
        context.addIssue({
          code: "custom",
          path: ["legs", index, "quantity"],
          message: "A close action must exactly clear remaining quantity",
        });
      } else {
        remaining = new Decimal(0);
        closed = true;
      }
    }
}

function validateTradeActivityIdentifiers(
  legs: z.infer<typeof tradeLegSchema>[],
  fundingCashflows: z.infer<typeof tradeCashflowSchema>[],
  context: z.RefinementCtx,
): void {
  const identifiers = new Set(legs.map((leg) => leg.id));
  for (const [index, cashflow] of fundingCashflows.entries()) {
    if (identifiers.has(cashflow.id)) {
      context.addIssue({
        code: "custom",
        path: ["fundingCashflows", index, "id"],
        message: "Trade activity IDs must be unique",
      });
    }
    identifiers.add(cashflow.id);
  }
}

export const tradeDraftSchema = tradeDraftBaseSchema.superRefine(
  ({ legs, fundingCashflows }, context) => {
    validateTradeLegAccounting(legs, context);
    validateTradeActivityIdentifiers(legs, fundingCashflows, context);
  },
);

export const tradeSchema = tradeDraftBaseSchema
  .extend({
    id: identifierSchema,
    status: tradeStatusSchema,
    netPnl: decimalStringSchema,
    openedAt: utcIsoStringSchema,
    closedAt: utcIsoStringSchema.nullable(),
    createdAt: utcIsoStringSchema,
    updatedAt: utcIsoStringSchema,
  })
  .superRefine(({ legs, fundingCashflows }, context) => {
    validateTradeLegAccounting(legs, context);
    validateTradeActivityIdentifiers(legs, fundingCashflows, context);
  });

export const tradeFiltersSchema = paginationSchema
  .extend({
    symbol: symbolSchema.optional(),
    direction: tradeDirectionSchema.optional(),
    horizon: tradeHorizonSchema.optional(),
    status: tradeStatusSchema.optional(),
    label: z.string().trim().min(1).optional(),
    from: utcIsoStringSchema.optional(),
    to: utcIsoStringSchema.optional(),
  })
  .refine(
    ({ from, to }) =>
      from === undefined || to === undefined || Date.parse(from) <= Date.parse(to),
    { message: "Trade filter start must not be after end", path: ["from"] },
  );

export type TradeDirection = z.infer<typeof tradeDirectionSchema>;
export type TradeHorizon = z.infer<typeof tradeHorizonSchema>;
export type TradeLegAction = z.infer<typeof tradeLegActionSchema>;
export type TradeStatus = z.infer<typeof tradeStatusSchema>;
export type TradeLeg = z.infer<typeof tradeLegSchema>;
export type TradeCashflow = z.infer<typeof tradeCashflowSchema>;
export type TradeDraft = z.infer<typeof tradeDraftSchema>;
export type Trade = z.infer<typeof tradeSchema>;
export type TradeFilters = z.input<typeof tradeFiltersSchema>;

export function parseTradeDraft(value: unknown): TradeDraft {
  return tradeDraftSchema.parse(value);
}
