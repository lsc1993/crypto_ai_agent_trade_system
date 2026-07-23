import { z } from "zod";

import { newsItemSchema } from "./news";
import {
  dataFreshnessSchema,
  decimalStringSchema,
  positiveDecimalStringSchema,
  symbolSchema,
  timeframeSchema,
  utcIsoStringSchema,
} from "./primitives";
import { analysisReportSummarySchema } from "./report";

export const marketSummarySchema = z.object({
  symbol: symbolSchema,
  price: positiveDecimalStringSchema,
  change24h: decimalStringSchema,
  volume24h: nonNegativeMarketMetricSchema(),
  fundingRate: decimalStringSchema,
  openInterest: nonNegativeMarketMetricSchema(),
  freshness: dataFreshnessSchema,
});

function nonNegativeMarketMetricSchema() {
  return z
    .string()
    .regex(/^(?:0|[1-9]\d*)(?:\.\d+)?$/)
    .refine((value) => {
      const parts = value.split(".");
      const integer = parts[0];
      const fraction = parts[1] ?? "";
      if (integer === undefined) {
        return false;
      }
      return integer.length + fraction.length <= 38 && fraction.length <= 18;
    });
}

export const candleSchema = z.object({
  symbol: symbolSchema,
  timeframe: timeframeSchema,
  openTime: utcIsoStringSchema,
  closeTime: utcIsoStringSchema,
  open: positiveDecimalStringSchema,
  high: positiveDecimalStringSchema,
  low: positiveDecimalStringSchema,
  close: positiveDecimalStringSchema,
  volume: nonNegativeMarketMetricSchema(),
});

export const candleSeriesSchema = z.object({
  timeframe: timeframeSchema,
  candles: z.array(candleSchema),
});

export const marketDetailSchema = z.object({
  summary: marketSummarySchema,
  series: z.array(candleSeriesSchema),
  news: z.array(newsItemSchema),
});

export const dashboardSnapshotSchema = z.object({
  markets: z.array(marketSummarySchema),
  news: z.array(newsItemSchema),
  recentReports: z.array(analysisReportSummarySchema),
  generatedAt: utcIsoStringSchema,
});

export type MarketSummary = z.infer<typeof marketSummarySchema>;
export type Candle = z.infer<typeof candleSchema>;
export type CandleSeries = z.infer<typeof candleSeriesSchema>;
export type MarketDetail = z.infer<typeof marketDetailSchema>;
export type DashboardSnapshot = z.infer<typeof dashboardSnapshotSchema>;
