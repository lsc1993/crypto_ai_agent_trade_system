import { parseWorkbenchConfig } from "../config/env";
import { HttpWorkbenchApi } from "./http-workbench-api";
import { MockWorkbenchApi } from "./mock-workbench-api";
import type { WorkbenchApi } from "./workbench-api";

export function createWorkbenchApi(
  environment?: unknown,
): WorkbenchApi {
  const runtimeEnvironment: unknown = import.meta.env;
  const config = parseWorkbenchConfig(environment ?? runtimeEnvironment);
  if (config.dataMode === "mock") {
    return new MockWorkbenchApi();
  }
  return new HttpWorkbenchApi({ baseUrl: config.apiBaseUrl });
}
