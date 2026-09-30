import { Link, useSearchParams } from "react-router-dom";

import "./technical-reports.css";

export function ReportStyleNavigation({ selected }: { selected: "comprehensive" | "technical" }) {
  const [params] = useSearchParams();
  const symbol = params.get("symbol");
  const query = symbol === null ? "" : `?symbol=${encodeURIComponent(symbol)}`;
  return <nav className="report-style-navigation" aria-label="研究报告风格">
    <Link to={`/reports${query}`} aria-current={selected === "comprehensive" ? "page" : undefined}>
      <strong>综合研究</strong><span>行情、新闻与双周期观点</span>
    </Link>
    <Link to={`/technical-reports${query}`} aria-current={selected === "technical" ? "page" : undefined}>
      <strong>技术分析</strong><span>Skill 量价方法与条件研究计划</span>
    </Link>
  </nav>;
}
