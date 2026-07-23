import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import App from "../../app/App";
import { HttpWorkbenchApi } from "../api/http-workbench-api";
import { MockWorkbenchApi } from "../api/mock-workbench-api";
import { mockTradeDraft } from "./fixtures";

describe("Mock mode controls", () => {
  it("renders the visible mode label and resets the active Mock API in memory", async () => {
    const user = userEvent.setup();
    const api = new MockWorkbenchApi();
    const seed = await api.listTrades({ page: 1, pageSize: 20 });
    await api.createTrade(mockTradeDraft);
    const changed = await api.listTrades({ page: 1, pageSize: 20 });
    expect(changed.total).toBe(seed.total + 1);

    render(<App dataMode="mock" api={api} />);

    expect(screen.getByText("Mock 数据模式")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "重置 Mock 数据" }));
    await expect(
      api.listTrades({ page: 1, pageSize: 20 }),
    ).resolves.toEqual(seed);
  });

  it("does not render Mock controls in API mode", () => {
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
    });
    render(<App dataMode="api" api={api} />);

    expect(screen.queryByText("Mock 数据模式")).not.toBeInTheDocument();
  });
});
