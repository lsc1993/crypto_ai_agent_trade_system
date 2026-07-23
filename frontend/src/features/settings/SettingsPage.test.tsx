import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { SettingsPage } from "./SettingsPage";
import {
  PREFERENCES_STORAGE_KEY,
  loadPreferences,
} from "./preferences-store";

describe("SettingsPage", () => {
  it("shows only Chinese display preference controls", () => {
    render(<SettingsPage />);

    expect(
      screen.getByRole("heading", { name: "设置" }),
    ).toBeVisible();
    expect(screen.getByLabelText("主题")).toHaveValue("system");
    expect(screen.getByLabelText("显示时区")).toHaveValue("UTC");
    expect(screen.getByLabelText("刷新偏好")).toHaveValue("manual");
    expect(
      screen.queryByLabelText(
        /账户|交易所|API|密钥|Secret|Passphrase|私钥|报告|草稿/,
      ),
    ).not.toBeInTheDocument();
  });

  it("persists the selected display preferences and nothing else", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.selectOptions(screen.getByLabelText("主题"), "light");
    await user.selectOptions(
      screen.getByLabelText("显示时区"),
      "Asia/Shanghai",
    );
    await user.selectOptions(
      screen.getByLabelText("刷新偏好"),
      "auto",
    );
    await user.click(
      screen.getByRole("button", { name: "保存显示偏好" }),
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "显示偏好已保存在当前浏览器。",
    );
    expect(loadPreferences()).toEqual({
      theme: "light",
      displayTimezone: "Asia/Shanghai",
      refreshPreference: "auto",
    });
    const raw = localStorage.getItem(PREFERENCES_STORAGE_KEY);
    expect(Object.keys(JSON.parse(raw ?? "{}") as object).sort()).toEqual([
      "displayTimezone",
      "refreshPreference",
      "theme",
    ]);
  });
});
