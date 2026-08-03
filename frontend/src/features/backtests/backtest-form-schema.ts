import {
  backtestRequestSchema,
  type BacktestRequest,
} from "../../domain/backtest";

export interface BacktestFormValues {
  startAt: string;
  endAt: string;
  initialCash: string;
}

export const defaultBacktestFormValues: BacktestFormValues = {
  startAt: "2026-06-01T00:00:00Z",
  endAt: "2026-07-01T00:00:00Z",
  initialCash: "10000",
};

export type ParsedBacktestForm =
  | { input: BacktestRequest; message: null }
  | { input: null; message: string };

export function parseBacktestForm(
  values: BacktestFormValues,
): ParsedBacktestForm {
  const parsed = backtestRequestSchema.safeParse({
    symbol: "BTCUSDT",
    timeframe: "1h",
    ...values,
  });
  if (parsed.success) {
    return { input: parsed.data, message: null };
  }

  return {
    input: null,
    message:
      "请检查回测参数：时间必须为 UTC ISO 格式，开始时间早于结束时间，初始资金为正数。",
  };
}
