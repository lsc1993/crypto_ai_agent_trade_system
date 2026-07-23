import { resetMockWorkbench } from "./reset";

export function MockModeControls() {
  return (
    <div role="status">
      <span>Mock 数据模式</span>
      <button type="button" onClick={resetMockWorkbench}>
        重置 Mock 数据
      </button>
    </div>
  );
}
