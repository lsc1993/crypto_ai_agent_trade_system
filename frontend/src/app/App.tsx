import { PageState } from "../components/common/PageState";
import { AppShell } from "../components/layout/AppShell";
import { MockWorkbenchApi } from "../shared/api/mock-workbench-api";
import type { WorkbenchApi } from "../shared/api/workbench-api";
import type {
  DataMode,
  WorkbenchConfigurationError,
} from "../shared/config/env";
import { AppProviders } from "./providers";
import { AppRouter } from "./router";

type ReadyAppProps =
  | {
      api: MockWorkbenchApi;
      dataMode: Extract<DataMode, "mock">;
      configurationError?: never;
    }
  | {
      api: WorkbenchApi;
      dataMode: Extract<DataMode, "api">;
      configurationError?: never;
    };

interface ConfigurationErrorAppProps {
  api?: never;
  dataMode?: never;
  configurationError: WorkbenchConfigurationError;
}

export type AppProps = ReadyAppProps | ConfigurationErrorAppProps;

function configurationErrorMessage(
  error: WorkbenchConfigurationError,
): string {
  return error.code === "INVALID_DATA_MODE"
    ? "数据模式配置无效，请将 VITE_DATA_MODE 设置为 mock 或 api。"
    : "API 地址配置无效，请检查 VITE_API_BASE_URL。";
}

export default function App(props: AppProps) {
  if (props.configurationError !== undefined) {
    return (
      <main id="main-content" className="configuration-error">
        <PageState
          state="error"
          message={configurationErrorMessage(props.configurationError)}
        />
      </main>
    );
  }

  const onResetMockData =
    props.dataMode === "mock"
      ? () => {
          props.api.reset();
        }
      : undefined;

  return (
    <AppProviders api={props.api}>
      <AppShell
        dataMode={props.dataMode}
        onResetMockData={onResetMockData}
      >
        <AppRouter />
      </AppShell>
    </AppProviders>
  );
}
