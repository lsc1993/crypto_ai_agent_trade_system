import { z } from "zod";

import { analysisReportSchema } from "../../domain/report";
import { identifierSchema, symbolSchema } from "../../domain/primitives";
import { tradeSchema } from "../../domain/trade";
import { mockReports, mockTrades } from "./fixtures";

export const mockStateSchema = z.object({
  reports: z.array(analysisReportSchema),
  trades: z.array(tradeSchema),
  analysisSymbols: z.record(identifierSchema, symbolSchema),
  nextAnalysisSequence: z.number().int().positive(),
  nextTradeSequence: z.number().int().positive(),
});

export type MockState = z.infer<typeof mockStateSchema>;

export function createMockSeed(): MockState {
  return mockStateSchema.parse({
    reports: mockReports,
    trades: mockTrades,
    analysisSymbols: {
      "analysis-btc-001": "BTCUSDT",
      "analysis-eth-001": "ETHUSDT",
    },
    nextAnalysisSequence: 1,
    nextTradeSequence: 2,
  });
}
