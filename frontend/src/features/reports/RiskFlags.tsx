export interface RiskFlagsProps {
  risks: string[];
  limitations: string[];
}

function renderItems(items: string[], emptyMessage: string) {
  if (items.length === 0) {
    return <p>{emptyMessage}</p>;
  }
  return (
    <ul>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export function RiskFlags({ risks, limitations }: RiskFlagsProps) {
  return (
    <div className="report-risk-grid">
      <section
        className="report-section report-section--risk"
        aria-labelledby="report-risks-title"
      >
        <h2 id="report-risks-title">风险标记</h2>
        {renderItems(risks, "未记录额外风险。")}
      </section>
      <section
        className="report-section report-section--limitation"
        aria-labelledby="report-limitations-title"
      >
        <h2 id="report-limitations-title">分析限制</h2>
        {renderItems(limitations, "未记录额外限制。")}
      </section>
    </div>
  );
}
