import { z } from "zod";

import {
  tradeDraftSchema,
  type TradeDraft,
} from "../../domain/trade";

const tradeLegEnvelopeSchema = z
  .object({
    id: z.unknown(),
    action: z.unknown(),
    executedAt: z.unknown(),
    price: z.unknown(),
    quantity: z.unknown(),
    fee: z.unknown(),
  })
  .strict();

const tradeDraftEnvelopeSchema = z
  .object({
    symbol: z.unknown(),
    direction: z.unknown(),
    horizon: z.unknown(),
    labels: z.unknown(),
    linkedReportId: z.unknown(),
    leverage: z.unknown(),
    legs: z.array(tradeLegEnvelopeSchema),
    fundingFee: z.unknown(),
    thesis: z.unknown(),
    review: z.unknown(),
  })
  .strict();

export function parseTradeFormDraft(value: unknown): TradeDraft {
  const envelope = tradeDraftEnvelopeSchema.parse(value);
  return tradeDraftSchema.parse(envelope);
}
