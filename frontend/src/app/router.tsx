import { Link, useParams, useRoutes } from "react-router-dom";

import { PageState } from "../components/common/PageState";

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

function MarketPage() {
  const { symbol = "" } = useParams();
  return (
    <RoutePage
      title={`${symbol} 市场详情`}
      description="查看所选标的的行情、K 线、新闻与数据新鲜度。"
    />
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
      element: (
        <RoutePage
          title="研究工作台"
          description="集中查看市场、研究报告、交易日志与复盘统计。"
        />
      ),
    },
    { path: "/market/:symbol", element: <MarketPage /> },
    {
      path: "/reports",
      element: (
        <RoutePage
          title="分析报告"
          description="浏览可审计的事实、推断、风险与限制。"
        />
      ),
    },
    {
      path: "/reports/:reportId",
      element: (
        <RoutePage
          title="报告详情"
          description="查看报告证据、数据截止时间和分析状态。"
        />
      ),
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
      element: (
        <RoutePage
          title="设置"
          description="管理工作台显示偏好，不涉及账户或交易所权限。"
        />
      ),
    },
    { path: "*", element: <NotFoundPage /> },
  ]);
}
