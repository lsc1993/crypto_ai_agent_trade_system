import { z } from "zod";

import { analysisReportSchema } from "../../domain/report";
import { tradeSchema } from "../../domain/trade";
import { mockReports, mockTrades } from "./fixtures";

export const mockStateSchema = z.object({
  reports: z.array(analysisReportSchema),
  trades: z.array(tradeSchema),
  nextAnalysisSequence: z.number().int().positive(),
  nextTradeSequence: z.number().int().positive(),
});

export type MockState = z.infer<typeof mockStateSchema>;

export function createMockSeed(): MockState {
  return mockStateSchema.parse({
    reports: mockReports,
    trades: mockTrades,
    nextAnalysisSequence: 1,
    nextTradeSequence: 2,
  });
}
