import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createRuntimeApplication } from "./app/bootstrap";
import "./styles/index.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("Application root element is missing");
}

createRoot(root).render(
  <StrictMode>
    {createRuntimeApplication(import.meta.env)}
  </StrictMode>,
);
