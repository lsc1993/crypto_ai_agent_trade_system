import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import { uuidSchema } from "../../domain/primitives";
import type { TechnicalReport } from "../../domain/technical-report";
import { MockWorkbenchApi } from "../../shared/api/mock-workbench-api";
import { errorLabel, percentLabel, priceLabel, reasonLabel } from "./technical-copy";
import "./technical-reports.css";

const directionLabels = { long: "条件做多", short: "条件做空", none: "未确认突破" } as const;
const trendLabels: Record<string, string> = { bullish: "上行", bearish: "下行", neutral: "中性" };
const volumeLabels: Record<string, string> = { high: "放量", low: "缩量", ordinary: "常态量" };

function Facts({ report }: { report: TechnicalReport }) {
  const facts = report.analysis.facts;
  if (facts === null) return <p>数据不足，未计算技术事实。</p>;
  return <>
    <dl className="technical-facts">
      <div><dt>多周期趋势</dt><dd>{["1d", "4h", "1h"].map((frame) => `${frame} ${trendLabels[facts.trendAlignment[frame] ?? ""] ?? "未知"}`).join(" · ")}</dd></div>
      <div><dt>1h 区间高 / 低</dt><dd>{priceLabel(facts.rangeHigh)} / {priceLabel(facts.rangeLow)}</dd></div>
      <div><dt>20 根基准相对量</dt><dd>{facts.volumeRatio} 倍 · {volumeLabels[facts.volumeSignal] ?? "未分类"}</dd></div>
      <div><dt>1h 收盘突破</dt><dd>{directionLabels[facts.breakout]}</dd></div>
      <div><dt>形态事实</dt><dd>{[facts.smallBody && "小实体", facts.longUpperWick && "长上影", facts.longLowerWick && "长下影"].filter(Boolean).join(" · ") || "无指定形态"}</dd></div>
      <div><dt>ATR14</dt><dd>{priceLabel(facts.atr14)}</dd></div>
      <div><dt>结构支撑</dt><dd>{facts.supportLevels.length === 0 ? "缺失" : facts.supportLevels.map(priceLabel).join(" · ")}</dd></div>
      <div><dt>结构阻力</dt><dd>{facts.resistanceLevels.length === 0 ? "缺失" : facts.resistanceLevels.map(priceLabel).join(" · ")}</dd></div>
    </dl>
    <div className="technical-moving-averages"><h3>SMA 背景</h3><ul>{["1d", "4h", "1h"].map((frame) => <li key={frame}>{frame}: SMA20 {facts.sma20[frame] === undefined ? "缺失" : priceLabel(facts.sma20[frame])} / SMA50 {facts.sma50[frame] === undefined ? "缺失" : priceLabel(facts.sma50[frame])}</li>)}</ul></div>
  </>;
}

function Plans({ report }: { report: TechnicalReport }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => { setNow(Date.now()); }, 30000);
    return () => { window.clearInterval(timer); };
  }, []);
  return <section className="technical-panel" aria-labelledby="technical-plans-title">
    <h2 id="technical-plans-title">条件研究计划</h2>
    <p>假设当前空仓。以下价格仅用于结构研究；不涉及账户、仓位、杠杆或订单。</p>
    {report.analysis.plans.length === 0 ? <p>当前无符合规则的计划。</p> : report.analysis.plans.map((plan, index) => <article className="technical-plan" key={`${plan.direction}-${index}`}>
      <header><h3>{directionLabels[plan.direction]}</h3><strong>{plan.state === "triggered" ? "历史已触发信号" : "等待后续确认"}</strong></header>
      {now >= Date.parse(plan.validUntil) ? <p className="technical-notice">已到期，请重新研究</p> : null}
      <p>{plan.state === "awaiting_confirmation" ? `后续 1h K 线须收盘${plan.direction === "long" ? "高于" : "低于"} ${priceLabel(plan.triggerLevel)}，且相对成交量达到 1.5 倍，才满足突破条件。` : `截至本报告数据截止时间，1h 收盘及成交量已确认突破 ${priceLabel(plan.triggerLevel)}；这是冻结的历史信号，不代表当前可执行。`}</p>
      <dl className="technical-plan__levels">
        <div><dt>入场区间</dt><dd>{priceLabel(plan.entryLower)} – {priceLabel(plan.entryUpper)}</dd></div>
        <div><dt>结构止损</dt><dd>{priceLabel(plan.stopLoss)}</dd></div>
        <div><dt>结构目标</dt><dd>{priceLabel(plan.target)}</dd></div>
        <div><dt>成本后盈亏比</dt><dd>{plan.rewardRisk}:1</dd></div>
        <div><dt>研究有效至（UTC）</dt><dd><time dateTime={plan.validUntil}>{plan.validUntil}</time></dd></div>
      </dl>
      <p>有效期截至数据截止后 4 小时；超过该时点需重新研究。手续费每侧 {percentLabel(plan.feeRatePerSide)}、滑点每侧 {percentLabel(plan.slippageRatePerSide)}，均为研究假设。未模拟成交、部分成交或回测表现。</p>
    </article>)}
    {report.analysis.noPlanReasons.length > 0 ? <ul>{report.analysis.noPlanReasons.map((code) => <li key={code}>{reasonLabel(code)}</li>)}</ul> : null}
  </section>;
}

export function TechnicalReportDetailPage() {
  const { reportId } = useParams();
  if (reportId === undefined || !uuidSchema.safeParse(reportId).success) return <PageState state="unavailable" message="技术报告 ID 无效。" />;
  return <TechnicalReportDetailContent key={reportId} reportId={reportId} />;
}

function TechnicalReportDetailContent({ reportId }: { reportId: string }) {
  const api = useWorkbenchApi();
  const query = useQuery({ queryKey: ["technical-report", reportId], queryFn: () => api.getTechnicalReport(reportId) });
  if (query.isPending) return <PageState state="loading" />;
  if (query.isError) return <PageState state="error" message="无法读取技术报告。报告可能不存在，或本地存储暂不可用。" />;
  const report = query.data;
  return <article className="research-page technical-report-detail">
    <header className="research-page__heading"><div><p className="route-page__kicker">{report.symbol} · {report.status === "completed" ? "已完成" : "已降级"}</p><h1>技术分析报告</h1><p>量价事实、条件计划及方法归因均属于本次已冻结的研究记录。</p></div><Link className="text-link" to={`/technical-reports?symbol=${encodeURIComponent(report.symbol)}`}>返回历史报告</Link></header>
    {api instanceof MockWorkbenchApi ? <p className="technical-notice">Mock 演示数据：未读取真实行情，也未调用 AI 模型。</p> : null}
    {report.errorCode !== null ? <p role="status" className="technical-notice">{errorLabel(report.errorCode)}</p> : null}
    <section className="technical-panel" aria-labelledby="technical-audit-title"><h2 id="technical-audit-title">报告与数据质量</h2><dl className="technical-facts">
      <div><dt>报告 ID</dt><dd>{report.id}</dd></div><div><dt>分析 ID</dt><dd>{report.analysisId}</dd></div><div><dt>版本</dt><dd>{report.version}</dd></div><div><dt>创建时间（UTC）</dt><dd><time dateTime={report.createdAt}>{report.createdAt}</time></dd></div><div><dt>数据截止（UTC）</dt><dd><time dateTime={report.dataCutoffAt}>{report.dataCutoffAt}</time></dd></div><div><dt>数据质量</dt><dd>{report.analysis.quality.status === "valid" ? "通过" : "不足"}</dd></div><div><dt>证据 ID</dt><dd>{report.analysis.evidenceId}</dd></div>
    </dl>{report.analysis.quality.reasons.length > 0 ? <ul>{report.analysis.quality.reasons.map((code) => <li key={code}>{reasonLabel(code)}</li>)}</ul> : null}<p>已收盘 K 线：{Object.entries(report.analysis.quality.candleCounts).map(([frame, count]) => `${frame} ${count}`).join(" · ") || "未达到要求"}</p></section>
    <section className="technical-panel" aria-labelledby="technical-facts-title"><h2 id="technical-facts-title">确定性量价事实</h2><Facts report={report} /></section>
    <Plans report={report} />
    <section className="technical-panel" aria-labelledby="technical-narrative-title"><h2 id="technical-narrative-title">定性研究叙事</h2>{report.narrative === null ? <p>模型叙事不可用；上方确定性事实与条件计划仍可独立复核。</p> : <><h3>主要判断</h3><p>{report.narrative.thesis.text}</p><p>证据引用：{report.narrative.thesis.evidenceIds.join("、")}</p><h3>反向情景</h3><p>{report.narrative.alternative.text}</p><p>证据引用：{report.narrative.alternative.evidenceIds.join("、")}</p><h3>风险</h3>{report.narrative.risks.map((risk, index) => <div key={index}><p>{risk.text}</p><p>证据引用：{risk.evidenceIds.join("、")}</p></div>)}</>}</section>
    <section className="technical-panel" aria-labelledby="technical-methods-title"><h2 id="technical-methods-title">方法与来源</h2>{report.analysis.methods.length === 0 ? <p>本次报告没有可用的技术方法输出。</p> : report.analysis.methods.map((method) => <div className="technical-method" key={`${method.id}-${method.version}`}><h3>{method.id} · {method.version}</h3><p>原始 Skill：{method.sourceSkillId}</p><p>{method.adaptationNote}</p><p>原文 SHA256：{method.sourceSha256}</p><p>改编 SHA256：{method.adaptedSha256}</p></div>)}</section>
  </article>;
}
