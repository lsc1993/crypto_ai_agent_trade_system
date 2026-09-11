import { NavLink, useMatch } from "react-router-dom";

const navigationItems = [
  { to: "/", label: "研究工作台", end: true },
  { to: "/reports", label: "分析报告", end: false },
  { to: "/research-symbols", label: "研究币对管理", end: false },
  { to: "/backtests", label: "策略回测", end: false },
  { to: "/paper-trading", label: "模拟盘", end: false },
  { to: "/trades", label: "交易日志", end: false },
  { to: "/analytics", label: "复盘统计", end: false },
  { to: "/settings", label: "设置", end: false },
] as const;

export interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const marketMatch = useMatch("/market/:symbol");
  const marketSymbol = marketMatch?.params.symbol ?? "BTCUSDT";
  const sidebarItems = [
    navigationItems[0],
    {
      to: `/market/${marketSymbol}`,
      label: `${marketSymbol} 市场`,
      end: false,
    },
    ...navigationItems.slice(1),
  ];

  return (
    <aside className="app-sidebar">
      <div className="app-sidebar__header">
        <div className="app-sidebar__brand" aria-hidden="true">
          CA
        </div>
        <button
          className="app-sidebar__toggle"
          type="button"
          aria-controls="primary-navigation"
          aria-expanded={!collapsed}
          onClick={onToggle}
        >
          {collapsed ? "展开主导航" : "收起主导航"}
        </button>
      </div>
      <nav
        id="primary-navigation"
        aria-label="主导航"
        hidden={collapsed}
      >
        <ul className="app-sidebar__list">
          {sidebarItems.map((item) => (
            <li key={item.to}>
              <NavLink
                className={({ isActive }) =>
                  isActive
                    ? "app-sidebar__link app-sidebar__link--active"
                    : "app-sidebar__link"
                }
                end={item.end}
                to={item.to}
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
