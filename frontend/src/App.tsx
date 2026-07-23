import type { DataMode } from "./shared/config/env";
import { MockModeControls } from "./shared/mocks/MockModeControls";

export interface AppProps {
  dataMode: DataMode;
}

export default function App({ dataMode }: AppProps) {
  return dataMode === "mock" ? <MockModeControls /> : null;
}
