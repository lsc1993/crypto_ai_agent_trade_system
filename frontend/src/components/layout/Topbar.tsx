import type { DataMode } from "../../shared/config/env";
import { MockModeControls } from "../../shared/mocks/MockModeControls";

export interface TopbarProps {
  dataMode: DataMode;
  onResetMockData?: (() => void) | undefined;
}

export function Topbar({ dataMode, onResetMockData }: TopbarProps) {
  return (
    <header className="app-topbar">
      <div>
        <p className="app-topbar__eyebrow">AI 加密货币研究系统</p>
        <p className="app-topbar__title">研究与复盘工作台</p>
      </div>
      <div className="app-topbar__status">
        <span className="research-only-badge">仅研究与模拟</span>
        {dataMode === "market-api" ? (
          <div role="status">
            <span>公开市场数据模式</span>
            <span>市场、报告、交易日志与统计使用本地 API；资讯仍为 Mock</span>
          </div>
        ) : dataMode === "mock" && onResetMockData !== undefined ? (
          <MockModeControls onReset={onResetMockData} />
        ) : null}
      </div>
    </header>
  );
}
