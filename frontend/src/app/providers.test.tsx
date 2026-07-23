import { render, screen } from "@testing-library/react";
import { use } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MockWorkbenchApi } from "../shared/api/mock-workbench-api";
import { AppProviders } from "./providers";

const pendingForever = new Promise<never>(() => undefined);

function SuspendedContent() {
  use(pendingForever);
  return null;
}

function BrokenContent(): never {
  throw new Error("internal provider failure must stay hidden");
}

describe("AppProviders global fallbacks", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("renders the standardized global loading fallback for suspended content", () => {
    render(
      <AppProviders api={new MockWorkbenchApi()}>
        <SuspendedContent />
      </AppProviders>,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "正在加载数据",
    );
  });

  it("renders a safe global error fallback without exposing internal details", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <AppProviders api={new MockWorkbenchApi()}>
        <BrokenContent />
      </AppProviders>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "工作台暂时无法显示，请刷新页面后重试。",
    );
    expect(
      screen.queryByText("internal provider failure must stay hidden"),
    ).not.toBeInTheDocument();
  });
});
