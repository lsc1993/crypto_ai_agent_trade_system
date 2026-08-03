import { Link, useRoutes } from "react-router-dom";

import { AnalyticsPage } from "../features/analytics/AnalyticsPage";
import { BacktestDetailPage } from "../features/backtests/BacktestDetailPage";
import { BacktestListPage } from "../features/backtests/BacktestListPage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { MarketPage } from "../features/market/MarketPage";
import { ReportDetailPage } from "../features/reports/ReportDetailPage";
import { ReportListPage } from "../features/reports/ReportListPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { TradeEditorPage } from "../features/trades/TradeEditorPage";
import { TradeListPage } from "../features/trades/TradeListPage";

function NotFoundPage() {
  return (
    <section className="route-page route-page--centered">
      <p className="route-page__kicker">404</p>
      <h1>页面未找到</h1>
      <p>请求的地址不存在，或页面尚未加入工作台。</p>
      <Link className="primary-link" to="/">
        返回研究工作台
      </Link>
    </section>
  );
}

export function AppRouter() {
  return useRoutes([
    {
      path: "/",
      element: <DashboardPage />,
    },
    { path: "/market/:symbol", element: <MarketPage /> },
    {
      path: "/reports",
      element: <ReportListPage />,
    },
    {
      path: "/reports/:reportId",
      element: <ReportDetailPage />,
    },
    { path: "/backtests", element: <BacktestListPage /> },
    {
      path: "/backtests/:backtestId",
      element: <BacktestDetailPage />,
    },
    { path: "/trades", element: <TradeListPage /> },
    { path: "/trades/new", element: <TradeEditorPage /> },
    {
      path: "/trades/:tradeId/edit",
      element: <TradeEditorPage />,
    },
    { path: "/analytics", element: <AnalyticsPage /> },
    {
      path: "/settings",
      element: <SettingsPage />,
    },
    { path: "*", element: <NotFoundPage /> },
  ]);
}
