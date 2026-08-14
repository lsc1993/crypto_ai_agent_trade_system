import type { AnalysisEvidence } from "../../domain/report";

export interface EvidenceListProps {
  evidence: AnalysisEvidence[];
}

export function EvidenceList({ evidence }: EvidenceListProps) {
  return (
    <section
      className="report-section evidence-list"
      aria-labelledby="report-evidence-title"
    >
      <h2 id="report-evidence-title">证据列表</h2>
      {evidence.length === 0 ? (
        <p>本报告没有可展示的证据快照。</p>
      ) : (
        <div className="evidence-list__items">
          {evidence.map((item) => (
            <article
              className="evidence-card"
              aria-label={`证据 ${item.id}`}
              id={`evidence-${item.id}`}
              key={item.id}
            >
              <p>{item.summary}</p>
              <dl className="metadata-list">
                <div>
                  <dt>不可变证据 ID</dt>
                  <dd>不可变证据 ID：{item.id}</dd>
                </div>
                <div>
                  <dt>来源</dt>
                  <dd>来源：{item.source}</dd>
                </div>
                <div>
                  <dt>观察时间</dt>
                  <dd>
                    观察时间：
                    <time dateTime={item.observedAt}>
                      {item.observedAt}
                    </time>
                  </dd>
                </div>
              </dl>
              <a
                className="text-link"
                href={item.sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                查看原始来源
              </a>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
