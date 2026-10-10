import type { TechnicalPlanReport } from "../../domain/technical-report";
import type { ReactNode } from "react";

const sections = [
  ["marketStructure", "市场结构与周期判断"], ["supportingEvidence", "支持证据"],
  ["counterEvidence", "冲突与反证"], ["entryConditions", "入场确认条件"],
  ["stopRationale", "止损依据"], ["targetRationale", "目标依据"],
  ["invalidation", "失效与取消条件"], ["alternative", "备选情景"],
  ["waitingConditions", "等待与重新评估"], ["methodApplications", "Skill 方法应用"], ["risks", "风险与适用限制"],
] as const;

export function TechnicalPlanBook({report, children}: {report: TechnicalPlanReport; children?: ReactNode}) {
  const stance = {long: "条件做多", short: "条件做空", wait: "等待确认"}[report.planBook.stance];
  return <section className="technical-panel" aria-labelledby="technical-book-title">
    <h2 id="technical-book-title">交易计划书 · {stance}</h2>
    <p>数据截止（UTC）：{report.dataCutoffAt}。计划仅对应本次冻结证据。</p>
    {report.generation.source === "rules" ? <p className="technical-notice">{report.generation.quality === "composition_fallback" ? "分析摘要已校验，正文由规则编排；模型编排未完成。" : "模型叙事不可用；以下为规则编排的事实与等待计划。"}</p> : <p>思考分析及报告编排已通过校验。</p>}
    <section><h3>等待与重新评估</h3>{report.planBook.waitingConditions.map((claim, index) => <p key={index}>{claim.text}</p>)}</section>
    {children}
    {sections.filter(([key]) => key !== "waitingConditions").map(([key, title]) => <section key={key}><h3>{title}</h3>{report.planBook[key].map((claim, index) => <div key={index}><p>{claim.text}</p><details><summary>查看依据</summary><p>证据：{claim.evidenceId}</p><p>事实：{claim.factRefs.join("、")}</p>{claim.methodRefs.length > 0 ? <p>方法：{claim.methodRefs.join("、")}</p> : null}</details></div>)}</section>)}
  </section>;
}
