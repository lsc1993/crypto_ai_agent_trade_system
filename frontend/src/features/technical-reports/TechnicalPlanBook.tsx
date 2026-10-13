import type { ReactNode } from "react";
import type { TechnicalPlanReport } from "../../domain/technical-report";
import { localizeClaimText, methodLabel, referenceLabel } from "./technical-presentation";
import { TechnicalMarketStructure } from "./TechnicalMarketStructure";

type Claim = TechnicalPlanReport["planBook"]["marketStructure"][number];

function Claims({claims}: {claims: Claim[]}) {
  return claims.length === 0 ? <p className="technical-caption">本次报告未提供该项分析。</p> : claims.map((claim, index) => <div className="technical-claim" key={index}>
    <p>{localizeClaimText(claim.text)}</p>
    <details className="technical-evidence"><summary>查看依据</summary>
      <p>事实：{claim.factRefs.map((ref) => referenceLabel(ref)).join("、") || "未引用具体字段"}</p>
      {claim.methodRefs.length > 0 ? <p>方法：{claim.methodRefs.map(methodLabel).join("、")}</p> : null}
      <details><summary>原始引用与证据标识</summary><p>证据：{claim.evidenceId}</p><p>字段路径：{claim.factRefs.join("、")}</p><p>方法标识：{claim.methodRefs.join("、") || "无"}</p></details>
    </details>
  </div>);
}

function BookSection({id, title, children}: {id: string; title: string; children: ReactNode}) {
  return <section className="technical-book-section" aria-labelledby={id}><h3 id={id}>{title}</h3>{children}</section>;
}

export function TechnicalPlanBook({report, children}: {report: TechnicalPlanReport; children?: ReactNode}) {
  const stance = {long: "条件做多", short: "条件做空", wait: "等待确认"}[report.planBook.stance];
  const book = report.planBook;
  return <section className="technical-panel technical-book" aria-labelledby="technical-book-title">
    <header className="technical-book-overview"><p className="technical-caption">结论概览 · 冻结研究记录</p><h2 id="technical-book-title">交易计划书 · {stance}</h2><p>数据截止（UTC）：{report.dataCutoffAt}。计划仅对应本次冻结证据。</p></header>
    {report.generation.source === "rules" ? <p className="technical-notice">{report.generation.quality === "composition_fallback" ? "分析摘要已校验，正文由规则编排；模型编排未完成。" : "模型叙事不可用；以下为规则编排的事实与等待计划。"}</p> : <p className="technical-caption">思考分析及报告编排已通过校验。</p>}
    <nav className="technical-book-nav" aria-label="交易计划书章节"><a href="#technical-waiting">等待条件</a><a href="#technical-plans-title">价格计划</a><a href="#technical-structure">市场结构</a><a href="#technical-evidence-support">支持与反证</a><a href="#technical-risks">风险限制</a></nav>
    <BookSection id="technical-waiting" title="等待与重新评估"><Claims claims={book.waitingConditions} /></BookSection>
    {children}
    <div className="technical-book-grid">
      <BookSection id="technical-entry" title="入场确认条件"><Claims claims={book.entryConditions} /></BookSection>
      <BookSection id="technical-invalidation" title="失效与取消条件"><Claims claims={book.invalidation} /></BookSection>
      <BookSection id="technical-stop" title="止损依据"><Claims claims={book.stopRationale} /></BookSection>
      <BookSection id="technical-target" title="目标依据"><Claims claims={book.targetRationale} /></BookSection>
    </div>
    <BookSection id="technical-structure" title="市场结构与周期判断"><TechnicalMarketStructure report={report} /><details className="technical-full-analysis"><summary>展开完整市场分析</summary><Claims claims={book.marketStructure} /></details></BookSection>
    <div className="technical-book-grid">
      <BookSection id="technical-evidence-support" title="支持证据"><Claims claims={book.supportingEvidence} /></BookSection>
      <BookSection id="technical-evidence-counter" title="冲突与反证"><Claims claims={book.counterEvidence} /></BookSection>
    </div>
    <BookSection id="technical-alternative" title="备选情景"><Claims claims={book.alternative} /></BookSection>
    <BookSection id="technical-method-applications" title="Skill 方法应用"><Claims claims={book.methodApplications} /></BookSection>
    <BookSection id="technical-risks" title="风险与适用限制"><Claims claims={book.risks} /></BookSection>
  </section>;
}
