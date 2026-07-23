import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./index.css";
import { parseWorkbenchConfig } from "./shared/config/env";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("Application root element is missing");
}

const runtimeEnvironment: unknown = import.meta.env;
const config = parseWorkbenchConfig(runtimeEnvironment);

createRoot(root).render(
  <StrictMode>
    <App dataMode={config.dataMode} />
  </StrictMode>,
);
