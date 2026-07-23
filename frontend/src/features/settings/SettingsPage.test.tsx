import {
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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

  it("keeps rendering with safe feedback when reading localStorage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException(
        "private storage read detail",
        "SecurityError",
      );
    });

    render(<SettingsPage />);

    expect(
      screen.getByRole("heading", { name: "设置" }),
    ).toBeVisible();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "无法读取浏览器显示偏好，已使用安全默认值。",
    );
    expect(alert).not.toHaveTextContent("private storage read detail");
  });

  it("keeps rendering with safe feedback when invalid data cannot be purged", () => {
    vi.spyOn(Storage.prototype, "getItem").mockReturnValue(
      JSON.stringify({
        theme: "system",
        displayTimezone: "UTC",
        refreshPreference: "manual",
        reports: [{ id: "must-not-persist" }],
      }),
    );
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new DOMException(
        "private storage purge detail",
        "SecurityError",
      );
    });

    render(<SettingsPage />);

    expect(
      screen.getByRole("heading", { name: "设置" }),
    ).toBeVisible();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "无法读取浏览器显示偏好，已使用安全默认值。",
    );
    expect(alert).not.toHaveTextContent("private storage purge detail");
  });

  it("keeps rendering with safe feedback when saving localStorage throws", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException(
        "private storage write detail",
        "QuotaExceededError",
      );
    });

    await user.click(
      screen.getByRole("button", { name: "保存显示偏好" }),
    );

    expect(
      screen.getByRole("heading", { name: "设置" }),
    ).toBeVisible();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "无法保存显示偏好，请检查浏览器存储权限。",
    );
    expect(alert).not.toHaveTextContent("private storage write detail");
  });

  it("rejects unexpected select values before they enter preference state", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    fireEvent.change(screen.getByLabelText("主题"), {
      target: { value: "neon" },
    });
    fireEvent.change(screen.getByLabelText("显示时区"), {
      target: { value: "Not/A-Timezone" },
    });
    fireEvent.change(screen.getByLabelText("刷新偏好"), {
      target: { value: "15-seconds" },
    });

    expect(screen.getByLabelText("主题")).toHaveValue("system");
    expect(screen.getByLabelText("显示时区")).toHaveValue("UTC");
    expect(screen.getByLabelText("刷新偏好")).toHaveValue("manual");

    await user.click(
      screen.getByRole("button", { name: "保存显示偏好" }),
    );
    expect(loadPreferences()).toEqual({
      theme: "system",
      displayTimezone: "UTC",
      refreshPreference: "manual",
    });
  });
});
