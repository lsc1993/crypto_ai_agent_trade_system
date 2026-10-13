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
import { TechnicalPlanBook } from "./TechnicalPlanBook";
import { TechnicalMarketStructure } from "./TechnicalMarketStructure";
import { localizeClaimText, methodLabel, periodLabels } from "./technical-presentation";

const directionLabels = { long: "条件做多", short: "条件做空", none: "未确认突破" } as const;

function Facts({ report }: { report: TechnicalReport }) {
  const facts = report.analysis.facts;
  if (facts === null) return <p>数据不足，未计算技术事实。</p>;
  return <>
    {report.version === "technical-v1" ? <TechnicalMarketStructure report={report} /> : <p className="technical-caption">周期趋势、均线及量能见上方市场结构；以下保留全部结构价位，便于复核。</p>}
    <details className="technical-full-analysis"><summary>完整结构支撑与阻力列表</summary><div className="technical-book-grid">
      <div><h3>结构支撑（USDT）</h3>{facts.supportLevels.length === 0 ? <p>缺失</p> : <ol className="technical-level-list">{facts.supportLevels.map((level, index) => <li key={index}>{priceLabel(level)}</li>)}</ol>}</div>
      <div><h3>结构阻力（USDT）</h3>{facts.resistanceLevels.length === 0 ? <p>缺失</p> : <ol className="technical-level-list">{facts.resistanceLevels.map((level, index) => <li key={index}>{priceLabel(level)}</li>)}</ol>}</div>
    </div></details>
  </>;
}

function Plans({ report }: { report: TechnicalReport }) {
  const selectedPlans = report.version === "technical-v2" && report.planBook.selectedPlanRef === null ? [] : report.analysis.plans;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => { setNow(Date.now()); }, 30000);
    return () => { window.clearInterval(timer); };
  }, []);
  return <section className="technical-panel" aria-labelledby="technical-plans-title">
    <h2 id="technical-plans-title">条件研究计划</h2>
    <p>假设当前空仓。以下价格仅用于结构研究；不涉及账户、仓位、杠杆或订单。</p>
    {selectedPlans.length === 0 ? <p>当前无已选定的价格计划，请查看等待条件。</p> : selectedPlans.map((plan, index) => <article className="technical-plan" key={`${plan.direction}-${index}`}>
      <header><h3>{directionLabels[plan.direction]}</h3><strong>{plan.state === "triggered" ? "历史已触发信号" : "等待后续确认"}</strong></header>
      {now >= Date.parse(plan.validUntil) ? <p className="technical-notice">已到期，请重新研究</p> : null}
      <p>{plan.state === "awaiting_confirmation" ? `后续 1小时 K 线须收盘${plan.direction === "long" ? "高于" : "低于"} ${priceLabel(plan.triggerLevel)}，且相对成交量达到 1.5 倍，才满足突破条件。` : `截至本报告数据截止时间，1小时收盘及成交量已确认突破 ${priceLabel(plan.triggerLevel)}；这是冻结的历史信号，不代表当前可执行。`}</p>
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
  const audit = <section className="technical-panel" aria-labelledby="technical-audit-title"><h2 id="technical-audit-title">报告与数据质量</h2>
    <p>数据质量：{report.analysis.quality.status === "valid" ? "通过" : "不足"}；版本：{report.version === "technical-v2" ? "交易计划书第二版" : "技术研究第一版"}。</p>
    {report.analysis.quality.reasons.length > 0 ? <ul>{report.analysis.quality.reasons.map((code) => <li key={code}>{reasonLabel(code)}</li>)}</ul> : null}
    <details className="technical-full-analysis"><summary>展开报告标识与采集记录</summary><dl className="technical-facts">
      <div><dt>报告标识</dt><dd>{report.id}</dd></div><div><dt>分析标识</dt><dd>{report.analysisId}</dd></div><div><dt>原始版本</dt><dd>{report.version}</dd></div><div><dt>创建时间（UTC）</dt><dd><time dateTime={report.createdAt}>{report.createdAt}</time></dd></div><div><dt>数据截止（UTC）</dt><dd><time dateTime={report.dataCutoffAt}>{report.dataCutoffAt}</time></dd></div><div><dt>证据标识</dt><dd>{report.analysis.evidenceId}</dd></div>
    </dl><p>已收盘 K 线：{Object.entries(report.analysis.quality.candleCounts).map(([frame, count]) => `${periodLabels[frame] ?? frame} ${count}根`).join(" · ") || "未达到要求"}</p></details></section>;
  return <article className="research-page technical-report-detail">
    <header className="research-page__heading"><div><p className="route-page__kicker">{report.symbol} · {report.status === "completed" ? "已完成" : "已降级"}</p><h1>技术分析报告</h1><p>量价事实、条件计划及方法归因均属于本次已冻结的研究记录。</p></div><Link className="text-link" to={`/technical-reports?symbol=${encodeURIComponent(report.symbol)}`}>返回历史报告</Link></header>
    {api instanceof MockWorkbenchApi ? <p className="technical-notice">Mock 演示数据：未读取真实行情，也未调用 AI 模型。</p> : null}
    {report.errorCode !== null ? <p role="status" className="technical-notice">{errorLabel(report.errorCode)}</p> : null}
    {report.version === "technical-v1" ? audit : null}
    {report.version === "technical-v2" ? <TechnicalPlanBook report={report}><Plans report={report} /></TechnicalPlanBook> : null}
    <section className="technical-panel" aria-labelledby="technical-facts-title"><h2 id="technical-facts-title">确定性量价事实</h2><Facts report={report} /></section>
    {report.version === "technical-v1" ? <Plans report={report} /> : null}
    {report.version === "technical-v1" ? <section className="technical-panel" aria-labelledby="technical-narrative-title"><h2 id="technical-narrative-title">定性研究叙事</h2>{report.narrative === null ? <p>模型叙事不可用；上方确定性事实与条件计划仍可独立复核。</p> : <><h3>主要判断</h3><p>{report.narrative.thesis.text}</p><p>证据引用：{report.narrative.thesis.evidenceIds.join("、")}</p><h3>反向情景</h3><p>{report.narrative.alternative.text}</p><p>证据引用：{report.narrative.alternative.evidenceIds.join("、")}</p><h3>风险</h3>{report.narrative.risks.map((risk, index) => <div key={index}><p>{risk.text}</p><p>证据引用：{risk.evidenceIds.join("、")}</p></div>)}</>}</section> : null}
    <section className="technical-panel" aria-labelledby="technical-methods-title"><h2 id="technical-methods-title">方法与来源</h2>{report.analysis.methods.length === 0 ? <p>本次报告没有可用的技术方法输出。</p> : report.analysis.methods.map((method) => <div className="technical-method" key={`${method.id}-${method.version}`}><h3>{methodLabel(method.id)}</h3><p>{localizeClaimText(method.adaptationNote)}</p><details className="technical-evidence"><summary>查看方法来源与指纹</summary><p>方法标识：{method.id} · {method.version}</p><p>原始 Skill：{method.sourceSkillId}</p><p>原文 SHA256：{method.sourceSha256}</p><p>改编 SHA256：{method.adaptedSha256}</p></details></div>)}</section>
    {report.version === "technical-v2" ? audit : null}
  </article>;
}
