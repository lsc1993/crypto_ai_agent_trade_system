export interface MockModeControlsProps {
  onReset: () => void;
}

export function MockModeControls({ onReset }: MockModeControlsProps) {
  return (
    <div role="status">
      <span>Mock 数据模式</span>
      <button type="button" onClick={onReset}>
        重置 Mock 数据
      </button>
    </div>
  );
}
