import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import App from "./app/App";
import { createWorkbenchApi } from "./shared/api/create-api";
import { MockWorkbenchApi } from "./shared/api/mock-workbench-api";
import {
  WorkbenchConfigurationError,
  parseWorkbenchConfig,
} from "./shared/config/env";
import "./styles/index.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("Application root element is missing");
}

function createApplication(): ReactNode {
  const runtimeEnvironment: unknown = import.meta.env;
  try {
    const config = parseWorkbenchConfig(runtimeEnvironment);
    const api = createWorkbenchApi(runtimeEnvironment);
    if (config.dataMode === "mock") {
      if (!(api instanceof MockWorkbenchApi)) {
        throw new Error("Mock data mode requires the Mock workbench API");
      }
      return <App api={api} dataMode="mock" />;
    }
    return <App api={api} dataMode="api" />;
  } catch (error: unknown) {
    if (error instanceof WorkbenchConfigurationError) {
      return <App configurationError={error} />;
    }
    throw error;
  }
}

createRoot(root).render(
  <StrictMode>{createApplication()}</StrictMode>,
);
