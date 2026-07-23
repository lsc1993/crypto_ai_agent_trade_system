import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import App from "../../App";
import { MOCK_STORAGE_KEY } from "./reset";

describe("Mock mode controls", () => {
  it("renders the visible mode label and resets Mock state", async () => {
    const user = userEvent.setup();
    localStorage.setItem(MOCK_STORAGE_KEY, '{"changed":true}');

    render(<App dataMode="mock" />);

    expect(screen.getByText("Mock 数据模式")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "重置 Mock 数据" }));
    expect(localStorage.getItem(MOCK_STORAGE_KEY)).toBeNull();
  });

  it("does not render Mock controls in API mode", () => {
    render(<App dataMode="api" />);

    expect(screen.queryByText("Mock 数据模式")).not.toBeInTheDocument();
  });
});
