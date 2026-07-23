import { useState, type ReactNode } from "react";

import type { DataMode } from "../../shared/config/env";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export interface AppShellProps {
  children: ReactNode;
  dataMode: DataMode;
  onResetMockData?: (() => void) | undefined;
}

export function AppShell({
  children,
  dataMode,
  onResetMockData,
}: AppShellProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <>
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <div
        className="app-shell"
        data-sidebar-collapsed={sidebarCollapsed}
      >
        <Sidebar
          collapsed={sidebarCollapsed}
          onToggle={() => {
            setSidebarCollapsed((collapsed) => !collapsed);
          }}
        />
        <div className="app-shell__workspace">
          <Topbar
            dataMode={dataMode}
            onResetMockData={onResetMockData}
          />
          <main id="main-content" tabIndex={-1}>
            {children}
          </main>
        </div>
      </div>
    </>
  );
}
