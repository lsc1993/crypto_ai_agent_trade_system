import Decimal from "decimal.js";

import { WorkbenchHttpError } from "../../shared/api/http-transport";
import { formatDecimal } from "../../shared/format";

const reasonMessages: Record<string, string> = {
  mock_demo_only: "Mock 演示数据，未读取真实行情或调用模型。",
  market_summary_not_fresh: "公开行情摘要未达到新鲜度要求。",
  market_summary_future_timestamp: "行情摘要时间晚于本次采集时间。",
  market_summary_stale_timestamp: "行情摘要已过期。",
  insufficient_candles: "已收盘 K 线不足 60 根。",
  missing_or_duplicate_series: "必要周期缺失或重复。",
  wrong_symbol: "K 线币对与请求不一致。",
  future_timestamp: "数据包含截止时间之后的记录。",
  invalid_duration: "K 线周期时长不正确。",
  gap_or_duplicate: "K 线存在断档或重复。",
  stale: "最近收盘 K 线已过期。",
  zero_volume_baseline: "成交量基准不足。",
  unsupported_price_precision: "价格精度超出报告契约。",
  trend_conflict: "日线、4 小时与 1 小时方向不一致。",
  opposite_breakout: "突破方向与主要趋势相反。",
  insufficient_volatility: "波动结构不足。",
  unconfirmed_breakout: "价格越过区间，但量能或收盘确认不足。",
  awaiting_distant_trigger: "当前价格离触发边界过远。",
  entry_too_far_from_range: "已远离入场区间，不追价。",
  no_structural_stop: "缺少可验证的结构止损。",
  no_structural_target: "缺少可验证的结构目标。",
  invalid_structure: "止损、入场和目标的结构顺序无效。",
  reward_risk_below_minimum: "计入成本后的盈亏比低于 1.5。",
  current_price_invalidates_plan: "最新价格已偏离入场条件，请重新研究。",
};

const errorMessages: Record<string, string> = {
  market_unavailable: "公开行情暂不可用。",
  data_quality_insufficient: "数据质量不足，无法形成可靠技术事实。",
  model_not_configured: "模型叙事不可用：尚未配置模型。",
  model_timeout: "模型叙事不可用：请求超时。",
  model_upstream_error: "模型叙事不可用：上游服务失败。",
  model_invalid_response: "模型叙事不可用：结果未通过校验。",
  model_output_limit: "模型输出额度耗尽，已保留规则结果。",
  model_empty_response: "模型正文为空，已保留可复核的规则结果。",
  run_timeout: "研究达到时间上限，已保留本次规则结果。",
};

export function reasonLabel(code: string): string {
  if (reasonMessages[code] !== undefined) return reasonMessages[code];
  const match = /^(1d|4h|1h)_(.+)$/.exec(code);
  if (match !== null) {
    const period = match[1] === "1d" ? "日线" : match[1] === "4h" ? "4 小时" : "1 小时";
    return `${period}：${reasonMessages[match[2] ?? ""] ?? "数据未通过质量校验。"}`;
  }
  return "当前证据未满足技术研究条件。";
}

export function errorLabel(code: string | null): string | null {
  return code === null ? null : (errorMessages[code] ?? "技术研究未完成。");
}

export function requestErrorLabel(error: unknown): string {
  if (error instanceof WorkbenchHttpError) {
    if (error.code === "research_symbol_archived") return "币对已归档，只能读取历史报告。";
    if (error.code === "research_symbol_sync_pending") return "币对数据仍在同步，请稍后重试。";
    if (error.code === "research_symbol_not_found") return "研究币对未登记。";
  }
  return "技术报告请求失败，请稍后重试。";
}

export function priceLabel(value: string): string {
  return formatDecimal(value);
}

export function percentLabel(value: string): string {
  return `${new Decimal(value).mul(100).toString()}%`;
}
