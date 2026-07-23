import { Link, useRoutes } from "react-router-dom";

import { PageState } from "../components/common/PageState";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { MarketPage } from "../features/market/MarketPage";
import { ReportDetailPage } from "../features/reports/ReportDetailPage";
import { ReportListPage } from "../features/reports/ReportListPage";
import { SettingsPage } from "../features/settings/SettingsPage";

interface RoutePageProps {
  title: string;
  description: string;
}

function RoutePage({ title, description }: RoutePageProps) {
  return (
    <section className="route-page">
      <div className="route-page__heading">
        <p className="route-page__kicker">工作台</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <PageState
        state="unavailable"
        message="当前仅提供应用外壳；数据功能将在对应模块接入后开放。"
      />
    </section>
  );
}

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
    {
      path: "/trades",
      element: (
        <RoutePage
          title="交易日志"
          description="记录模拟交易与复盘信息，不提供真实下单能力。"
        />
      ),
    },
    {
      path: "/trades/new",
      element: (
        <RoutePage
          title="新增交易记录"
          description="创建用于研究和复盘的模拟交易记录。"
        />
      ),
    },
    {
      path: "/trades/:tradeId/edit",
      element: (
        <RoutePage
          title="编辑交易记录"
          description="补充已有模拟交易记录的复盘内容。"
        />
      ),
    },
    {
      path: "/analytics",
      element: (
        <RoutePage
          title="复盘统计"
          description="查看由交易日志汇总的十进制绩效指标。"
        />
      ),
    },
    {
      path: "/settings",
      element: <SettingsPage />,
    },
    { path: "*", element: <NotFoundPage /> },
  ]);
}
