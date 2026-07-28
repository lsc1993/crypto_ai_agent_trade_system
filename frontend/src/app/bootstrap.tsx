import type { ReactNode } from "react";
import { z } from "zod";

import { createWorkbenchApi } from "../shared/api/create-api";
import { MockWorkbenchApi } from "../shared/api/mock-workbench-api";
import {
  WorkbenchConfigurationError,
  parseWorkbenchConfig,
} from "../shared/config/env";
import App from "./App";

const defaultDataMode = "mock";
const defaultApiBaseUrl = "http://localhost:8000";
const entrypointEnvironmentSchema = z.object({
  VITE_DATA_MODE: z.unknown().optional(),
  VITE_API_BASE_URL: z.unknown().optional(),
});

function applyEntrypointDefaults(environment: unknown): unknown {
  const parsed = entrypointEnvironmentSchema.parse(environment);

  return {
    VITE_DATA_MODE:
      parsed.VITE_DATA_MODE === undefined
        ? defaultDataMode
        : parsed.VITE_DATA_MODE,
    VITE_API_BASE_URL:
      parsed.VITE_API_BASE_URL === undefined
        ? defaultApiBaseUrl
        : parsed.VITE_API_BASE_URL,
  };
}

export function createRuntimeApplication(
  environment: unknown,
): ReactNode {
  const runtimeEnvironment = applyEntrypointDefaults(environment);

  try {
    const config = parseWorkbenchConfig(runtimeEnvironment);
    const api = createWorkbenchApi(runtimeEnvironment);
    if (config.dataMode === "mock") {
      if (!(api instanceof MockWorkbenchApi)) {
        throw new Error("Mock data mode requires the Mock workbench API");
      }
      return <App api={api} dataMode="mock" />;
    }
    return <App api={api} dataMode={config.dataMode} />;
  } catch (error: unknown) {
    if (error instanceof WorkbenchConfigurationError) {
      return <App configurationError={error} />;
    }
    throw error;
  }
}
