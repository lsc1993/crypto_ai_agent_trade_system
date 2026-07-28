import { parseWorkbenchConfig } from "../config/env";
import { HybridWorkbenchApi } from "./hybrid-workbench-api";
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
  const httpApi = new HttpWorkbenchApi({ baseUrl: config.apiBaseUrl });
  if (config.dataMode === "market-api") {
    return new HybridWorkbenchApi(new MockWorkbenchApi(), httpApi);
  }
  return httpApi;
}
