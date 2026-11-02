import type { ResearchSymbolEntry } from "../../domain/research-symbol";

const failureMessages: Readonly<Record<string, string>> = {
  sync_timeout: "同步任务超时，请稍后重试。",
  sync_interrupted: "同步任务已中断，请重试。",
  sync_lease_expired: "同步任务租约已过期，请重试。",
  market_sync_failed: "公开行情同步失败，请稍后重试。",
  research_symbol_archived: "研究币对已归档，无法继续同步。",
};

const sourceNames = {
  market: "公开行情", candles: "K 线", derivatives: "衍生品",
  funding: "资金费率", news: "新闻", sentiment: "情绪", etf: "ETF",
};

const coverageLabels = {
  available: "可用", partial: "部分覆盖", missing: "缺失",
  failed: "失败", unsupported: "不支持",
};

export function ResearchSymbolSyncDiagnostics({ run }: {
  run: NonNullable<ResearchSymbolEntry["lastSync"]>;
}) {
  const times = [
    { label: "创建时间（UTC）", value: run.createdAt },
    { label: "开始时间（UTC）", value: run.startedAt },
    { label: "结束时间（UTC）", value: run.completedAt },
  ];
  // 仅映射白名单代码；服务端原始错误、stage 与来源 message/payload 均不能作为展示文本。
  const failure = run.error && Object.hasOwn(failureMessages, run.error)
    ? failureMessages[run.error]
    : "同步出现未知故障，请稍后重试。";

  return (
    <div aria-label="同步诊断">
      {times.some(({ value }) => value) ? times.map(({ label, value }) => value ? (
        <p key={label}>{label}：<time dateTime={value}>{value}</time></p>
      ) : null) : <p>同步时间未提供。</p>}
      {run.status === "failed" || run.error ? <p>失败原因：{failure}</p> : null}
      {run.sources?.length ? (
        <ul aria-label="来源覆盖">
          {run.sources.map((source) => (
            <li key={source.name}>{sourceNames[source.name]}：{coverageLabels[source.status]}</li>
          ))}
        </ul>
      ) : <p>来源覆盖未提供。</p>}
    </div>
  );
}
