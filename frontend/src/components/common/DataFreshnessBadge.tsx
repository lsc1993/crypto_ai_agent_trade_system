import type { DataFreshness } from "../../domain/primitives";

export type DataFreshnessBadgeProps = DataFreshness;

const statusLabels: Record<DataFreshness["status"], string> = {
  fresh: "数据正常",
  stale: "数据陈旧",
  missing: "数据缺失",
  failed: "数据获取失败",
};

export function DataFreshnessBadge({
  status,
  source,
  observedAt,
  fetchedAt,
}: DataFreshnessBadgeProps) {
  const label = statusLabels[status];

  return (
    <div
      className={`freshness-badge freshness-badge--${status}`}
      role="status"
      aria-label={`数据新鲜度：${label}`}
    >
      <strong className="freshness-badge__status">{label}</strong>
      <span className="freshness-badge__source">来源：{source}</span>
      <span>
        观察时间：
        <time dateTime={observedAt}>{observedAt}</time>
      </span>
      <span>
        获取时间：
        <time dateTime={fetchedAt}>{fetchedAt}</time>
      </span>
    </div>
  );
}
