import type { DataMode } from "./shared/config/env";
import type { MockWorkbenchApi } from "./shared/api/mock-workbench-api";
import { MockModeControls } from "./shared/mocks/MockModeControls";

export type AppProps =
  | {
      dataMode: Extract<DataMode, "mock">;
      mockApi: MockWorkbenchApi;
    }
  | {
      dataMode: Extract<DataMode, "api">;
      mockApi?: never;
    };

export default function App(props: AppProps) {
  return props.dataMode === "mock" ? (
    <MockModeControls
      onReset={() => {
        props.mockApi.reset();
      }}
    />
  ) : null;
}
