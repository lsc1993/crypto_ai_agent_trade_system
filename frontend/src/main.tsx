import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./index.css";
import { createWorkbenchApi } from "./shared/api/create-api";
import { MockWorkbenchApi } from "./shared/api/mock-workbench-api";
import { parseWorkbenchConfig } from "./shared/config/env";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("Application root element is missing");
}

const runtimeEnvironment: unknown = import.meta.env;
const config = parseWorkbenchConfig(runtimeEnvironment);
const api = createWorkbenchApi(runtimeEnvironment);
let application: ReactNode;
if (config.dataMode === "mock") {
  if (!(api instanceof MockWorkbenchApi)) {
    throw new Error("Mock data mode requires the Mock workbench API");
  }
  application = <App dataMode="mock" mockApi={api} />;
} else {
  application = <App dataMode="api" />;
}

createRoot(root).render(
  <StrictMode>{application}</StrictMode>,
);
