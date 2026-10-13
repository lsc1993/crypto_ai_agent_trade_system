import { reasonLabel } from "./technical-copy";

export const periodLabels: Record<string, string> = { "1d": "日线", "4h": "4小时", "1h": "1小时" };
export const trendLabels: Record<string, string> = { bullish: "上行", bearish: "下行", neutral: "中性" };
export const volumeLabels: Record<string, string> = { high: "放量", low: "缩量", ordinary: "常态量" };
export const methodLabels: Record<string, string> = {
  volume_price: "量价分析", range_breakout: "区间突破", multi_timeframe: "多周期确认", reversal: "反转形态观察",
};
const fieldLabels: Record<string, string> = {
  summaryPrice: "摘要价格", dataCutoffAt: "数据截止（UTC）", atr14: "平均真实波幅（14根）",
  rangeHigh: "区间高点（USDT）", rangeLow: "区间低点（USDT）", volumeRatio: "相对成交量（倍）",
  volumeSignal: "成交量状态", breakout: "收盘突破方向", smallBody: "小实体", longUpperWick: "长上影", longLowerWick: "长下影",
  triggerLevel: "突破确认价格（USDT）", entryLower: "入场区间下沿（USDT）", entryUpper: "入场区间上沿（USDT）",
  stopLoss: "结构止损（USDT）", target: "结构目标（USDT）", rewardRisk: "成本后盈亏比",
  feeRatePerSide: "每侧手续费率", slippageRatePerSide: "每侧滑点率", validUntil: "计划有效至（UTC）",
  state: "冻结信号状态", direction: "计划方向", rationale: "计划依据",
};

/** Display labels only: never alter persisted claims, numeric values or reference validation. */
export function referenceLabel(path: string, indexed = true): string {
  const period = /^(facts\.(trendAlignment|sma20|sma50)|latestClosedPrices)\.(1d|4h|1h)$/.exec(path);
  if (period) {
    const role = period[2] === "trendAlignment" ? "趋势" : period[2] === "sma20" ? "20根简单均线" : period[2] === "sma50" ? "50根简单均线" : "最新收盘价";
    return `${periodLabels[period[3] ?? ""]}${role}`;
  }
  const array = /^(facts\.(supportLevels|resistanceLevels)|noPlanReasons)\.(\d+)$/.exec(path);
  if (array) {
    const name = array[2] === "supportLevels" ? "结构支撑位" : array[2] === "resistanceLevels" ? "结构阻力位" : "等待原因";
    return name + (indexed ? `（第${Number(array[3]) + 1}项）` : "");
  }
  const field = /^(?:facts\.|plans\.\d+\.)?([A-Za-z][A-Za-z0-9]*)$/.exec(path)?.[1];
  return field === undefined ? path : (fieldLabels[field] ?? path);
}
const enums: Record<string, string> = {
  ...trendLabels, ...volumeLabels, ...methodLabels,
  long: "做多方向", short: "做空方向", none: "未确认突破", wait: "等待确认",
  triggered: "历史已触发信号", awaiting_confirmation: "等待后续确认",
  closed_volume_breakout_with_structural_target: "收盘与量能已确认突破，并存在结构目标",
  awaiting_closed_volume_breakout_with_structural_target: "等待收盘与量能确认突破，并存在结构目标",
};
const referencePattern = /(?<![A-Za-z0-9_.])(?:facts\.[A-Za-z][A-Za-z0-9]*(?:\.(?:1d|4h|1h|\d+))?|plans\.\d+\.[A-Za-z]+|noPlanReasons\.\d+|latestClosedPrices\.(?:1d|4h|1h)|summaryPrice|dataCutoffAt)(?![A-Za-z0-9_.])/g;

export function localizeClaimText(text: string): string {
  // Whole tokens only: avoid replacing substrings, unknown codes, decimal digits or prose.
  let result = text.replace(referencePattern, (path) => referenceLabel(path, false));
  result = result.replace(/(收盘突破方向)(\s*[：:]\s*)(long|short)(?![A-Za-z0-9_]|\.[A-Za-z0-9_])/g,
    (_, label: string, colon: string, value: string) => `${label}${colon}${value === "long" ? "向上突破" : "向下突破"}`);
  result = result.replace(/(小实体|长上影|长下影)(\s*[：:]\s*)(True|False|true|false)\b/g,
    (_, label: string, colon: string, value: string) => `${label}${colon}${value.toLowerCase() === "true" ? "已识别" : "未识别"}`);
  result = result.replace(/(?<![A-Za-z0-9_.])(?:(?:1d|4h|1h)_[A-Za-z_]+|[A-Za-z][A-Za-z0-9_]*)(?![A-Za-z0-9_]|\.[A-Za-z0-9_])/g, (token) => {
    if (enums[token] !== undefined) return enums[token];
    const translated = reasonLabel(token);
    return translated === "当前证据未满足技术研究条件。" ? token : translated.replace(/。$/, "");
  });
  return result.replace(/(?<![A-Za-z0-9_.])(1d|4h|1h)(?![A-Za-z0-9_]|\.[A-Za-z0-9_])/g, (period) => periodLabels[period] ?? period);
}
export function methodLabel(id: string): string {
  return methodLabels[id] ?? "技术研究方法";
}
