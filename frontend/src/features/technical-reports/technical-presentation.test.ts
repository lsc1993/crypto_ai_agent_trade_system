import { describe, expect, it } from "vitest";
import { localizeClaimText, referenceLabel } from "./technical-presentation";

describe("Chinese technical references", () => {
  it.each([
    ["facts.atr14", "平均真实波幅（14根）"], ["facts.rangeHigh", "区间高点（USDT）"],
    ["facts.rangeLow", "区间低点（USDT）"], ["facts.volumeRatio", "相对成交量（倍）"],
    ["facts.volumeSignal", "成交量状态"], ["facts.breakout", "收盘突破方向"],
    ["facts.smallBody", "小实体"], ["facts.longUpperWick", "长上影"], ["facts.longLowerWick", "长下影"],
    ["facts.trendAlignment.1d", "日线趋势"], ["facts.sma20.4h", "4小时20根简单均线"], ["facts.sma50.1h", "1小时50根简单均线"],
    ["facts.supportLevels.0", "结构支撑位（第1项）"], ["facts.resistanceLevels.12", "结构阻力位（第13项）"],
    ["noPlanReasons.2", "等待原因（第3项）"], ["summaryPrice", "摘要价格"], ["latestClosedPrices.1d", "日线最新收盘价"],
    ["dataCutoffAt", "数据截止（UTC）"], ["plans.0.direction", "计划方向"], ["plans.0.state", "冻结信号状态"],
    ["plans.0.triggerLevel", "突破确认价格（USDT）"], ["plans.0.entryLower", "入场区间下沿（USDT）"],
    ["plans.0.entryUpper", "入场区间上沿（USDT）"], ["plans.0.stopLoss", "结构止损（USDT）"], ["plans.0.target", "结构目标（USDT）"],
    ["plans.0.rewardRisk", "成本后盈亏比"], ["plans.0.feeRatePerSide", "每侧手续费率"], ["plans.0.slippageRatePerSide", "每侧滑点率"],
    ["plans.0.validUntil", "计划有效至（UTC）"], ["plans.0.rationale", "计划依据"],
  ])("labels %s in both inline text and evidence", (path, chinese) => {
    expect(referenceLabel(path)).toBe(chinese);
    expect(localizeClaimText(`${path}：0.123456789`)).not.toContain(path);
    expect(localizeClaimText(`${path}：0.123456789`)).toContain("0.123456789");
  });

  it("translates enums and methods as whole tokens, preserving unknown references and timestamps", () => {
    expect(localizeClaimText("bearish neutral low ordinary short triggered range_breakout multi_timeframe reversal 1d 4h 1h"))
      .toBe("下行 中性 缩量 常态量 做空方向 历史已触发信号 区间突破 多周期确认 反转形态观察 日线 4小时 1小时");
    const unknown = "facts.futureField.1h：unknown_code；highlight bullishness；2026-10-10T01:00:00Z；0.00000001";
    expect(localizeClaimText(unknown)).toBe(unknown);
    expect(localizeClaimText("facts.longUpperWick：True；facts.longLowerWick：false；noPlanReasons.1：1h_gap_or_duplicate"))
      .toBe("长上影：已识别；长下影：未识别；等待原因：1 小时：K 线存在断档或重复");
  });

  it("recognizes sentence punctuation without translating parts of unknown paths", () => {
    expect(localizeClaimText("facts.trendAlignment.1h: bullish. trend_conflict. 1h."))
      .toBe("1小时趋势: 上行. 日线、4 小时与 1 小时方向不一致. 1小时.");
    expect(localizeClaimText("facts.futureField.bullish" )).toBe("facts.futureField.bullish");
  });

  it("distinguishes breakout movement from the plan direction", () => {
    expect(localizeClaimText("facts.breakout：long；plans.0.direction：long；facts.breakout：short"))
      .toBe("收盘突破方向：向上突破；计划方向：做多方向；收盘突破方向：向下突破");
  });
});
