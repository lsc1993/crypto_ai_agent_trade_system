import { technicalReportV1Schema, technicalReportV2Schema } from "../domain/technical-report";
import { technicalReportWire } from "./technical-report-fixture";

const base = technicalReportV1Schema.omit({narrative: true}).strip().parse(technicalReportWire);
const analysis = {
  ...base.analysis, plans: [], noPlanReasons: ["trend_conflict"],
  facts: {
    ...base.analysis.facts,
    trendAlignment: {"1d": "bearish", "4h": "bullish", "1h": "bullish"},
    sma20: {"1d": "69000", "4h": "70000.12", "1h": "70120.32"},
    sma50: {"1d": "72000", "4h": "69500.24", "1h": "70000.64"},
    atr14: "200", rangeHigh: "70300", rangeLow: "68000", volumeRatio: "0.62", volumeSignal: "low",
    smallBody: false, longUpperWick: false, longLowerWick: true, breakout: "none",
    supportLevels: ["69000", "68000"], resistanceLevels: ["72000.12345678", "73000"],
  },
};
function claim(text: string, factRefs: string[]) {
  return {text, factRefs, evidenceId: analysis.evidenceId, methodRefs: ["volume_price"]};
}
const book = {
  stance: "wait", selectedPlanRef: null,
  waitingConditions: [claim("等待原因来自 noPlanReasons.0：trend_conflict。日线与短周期方向尚未形成一致证据，应等待后续已收盘行情重新确认，再评估是否出现可复核的价格计划。", ["noPlanReasons.0"])],
  marketStructure: [claim("日线背景仍偏弱，facts.trendAlignment.1d：bearish；短周期修复较强，facts.trendAlignment.4h：bullish，facts.trendAlignment.1h：bullish。当前应区分短周期反弹与更大周期趋势变化，不能将局部上行直接推断为全面反转。facts.sma20.1d：69000 与 facts.sma50.1d：72000 提供日线均线背景；完整分析保留这些冻结事实以便逐项复核。", ["facts.trendAlignment.1d", "facts.trendAlignment.4h", "facts.trendAlignment.1h", "facts.sma20.1d", "facts.sma50.1d"])],
  supportingEvidence: [claim("短周期趋势处于上行状态，facts.trendAlignment.1h：bullish；facts.longLowerWick：True 提示下影形态，可作为后续观察线索，但仍需等待进一步确认。", ["facts.trendAlignment.1h", "facts.longLowerWick"])],
  counterEvidence: [claim("facts.volumeSignal：low，facts.volumeRatio：0.62；facts.breakout：none。量能偏弱且尚未确认突破，削弱当前短周期上行信号的说服力。", ["facts.volumeSignal", "facts.volumeRatio", "facts.breakout"])],
  entryConditions: [claim("本次没有选定价格计划。只有趋势冲突得到解决且收盘与量能确认充分，才重新研究入场条件。", ["facts.breakout"])],
  stopRationale: [claim("当前等待状态不指定止损价格，结构支撑仅作为复核依据。", ["facts.supportLevels.0"])],
  targetRationale: [claim("facts.resistanceLevels.0：72000.12345678 是冻结的结构阻力位，并非本次已选定目标。", ["facts.resistanceLevels.0"])],
  invalidation: [claim("若短周期修复消失，应取消当前观察情景并重新研究。", ["facts.trendAlignment.1h"])],
  alternative: [claim("若日线维持下行背景，短周期修复可能仅为反弹，需继续观察冲突如何演变。", ["facts.trendAlignment.1d"])],
  methodApplications: [claim("volume_price 用于区分量能支持与反证；当前缩量背景不足以独立确认有效突破。", ["facts.volumeSignal"])],
  risks: [claim("冻结数据不代表当前状态。周期冲突可能延续，后续波动也可能使观察情景失效。", ["noPlanReasons.0"])],
};
export const readableTechnicalReport = technicalReportV2Schema.parse({
  ...base, version: "technical-v2", analysis,
  context: {analysis, summaryPrice: "70200", latestClosedPrices: {"1d": "69000", "4h": "70000", "1h": "70200"}, dataCutoffAt: base.dataCutoffAt},
  decision: book, planBook: book,
  generation: {source: "model", quality: "complete", promptVersion: "technical-plan-1", diagnostics: []},
});
