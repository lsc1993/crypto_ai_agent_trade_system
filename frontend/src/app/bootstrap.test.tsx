import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { createRuntimeApplication } from "./bootstrap";

function findDashboardHeading() {
  return screen.findByRole(
    "heading",
    { name: "研究工作台" },
    { timeout: 3_000 },
  );
}

describe("production runtime bootstrap", () => {
  it("starts a clean checkout in Mock mode when runtime keys are omitted", async () => {
    render(createRuntimeApplication({}));

    expect(await findDashboardHeading()).toBeVisible();
    expect(screen.getByText("Mock 数据模式")).toBeVisible();
  });

  it("defaults an independently omitted data mode without replacing an explicit base URL", async () => {
    render(
      createRuntimeApplication({
        VITE_API_BASE_URL: "http://127.0.0.1:9000",
      }),
    );

    expect(await findDashboardHeading()).toBeVisible();
    expect(screen.getByText("Mock 数据模式")).toBeVisible();
  });

  it("renders a safe visible configuration error for an explicit invalid mode", () => {
    render(
      createRuntimeApplication({
        VITE_API_BASE_URL: "http://localhost:8000",
        VITE_DATA_MODE: "live",
      }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "数据模式配置无效，请将 VITE_DATA_MODE 设置为 mock、market-api 或 api。",
    );
  });

  it("renders a safe visible configuration error for an explicit invalid base URL", () => {
    render(
      createRuntimeApplication({
        VITE_API_BASE_URL: "file:///tmp/workbench",
        VITE_DATA_MODE: "mock",
      }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "API 地址配置无效，请检查 VITE_API_BASE_URL。",
    );
  });
});
