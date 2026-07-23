import type { MockWorkbenchApi } from "./shared/api/mock-workbench-api";
import TaskApp from "./app/App";

export type AppProps =
  | {
      dataMode: "mock";
      mockApi: MockWorkbenchApi;
    }
  | {
      dataMode: "api";
      mockApi?: never;
    };

export default function App(props: AppProps) {
  if (props.dataMode === "api") {
    return null;
  }
  return <TaskApp api={props.mockApi} dataMode="mock" />;
}
