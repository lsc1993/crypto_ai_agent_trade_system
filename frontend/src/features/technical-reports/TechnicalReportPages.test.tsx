import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { TechnicalRun } from "../../domain/technical-report";
import { queuedRun } from "../../test/technical-run-fixture";

import { AppProviders } from "../../app/providers";
import { technicalReportWire } from "../../test/technical-report-fixture";
import { technicalReportSchema, type TechnicalReport } from "../../domain/technical-report";
import type { Page } from "../../domain/primitives";
import { MockWorkbenchApi } from "../../shared/api/mock-workbench-api";
import { TechnicalReportDetailPage } from "./TechnicalReportDetailPage";
import { TechnicalReportListPage } from "./TechnicalReportListPage";

const completed = technicalReportSchema.parse(technicalReportWire);

class CompletedTechnicalApi extends MockWorkbenchApi {
  override listTechnicalReports(): Promise<Page<TechnicalReport>> {
    return Promise.resolve({ items: [completed], page: 1, pageSize: 20, total: 1 });
  }
  override getTechnicalReport(): Promise<TechnicalReport> {
    return Promise.resolve(completed);
  }
}

function renderPages(api: MockWorkbenchApi, path: string) {
  window.history.replaceState({}, "", path);
  render(
    <AppProviders api={api}>
      <Routes>
        <Route path="/technical-reports" element={<TechnicalReportListPage />} />
        <Route path="/technical-reports/:reportId" element={<TechnicalReportDetailPage />} />
      </Routes>
    </AppProviders>,
  );
}

describe("independent technical reports", () => {
  it("keeps historical facts readable with Chinese methods and expandable complete price levels", async () => {
    renderPages(new CompletedTechnicalApi(), `/technical-reports/${completed.id}`);
    const facts = await screen.findByRole("region", {name: "确定性量价事实"});
    expect(within(facts).getByRole("table", {name: "多周期趋势对照"})).toBeInTheDocument();
    const levels = within(facts).getByText("完整结构支撑与阻力列表").closest("details");
    expect(levels).not.toHaveAttribute("open");
    await userEvent.setup().click(within(facts).getByText("完整结构支撑与阻力列表"));
    expect(levels).toHaveTextContent("72,000");
    expect(screen.getByRole("heading", {name: "量价分析"})).toBeInTheDocument();
    expect(screen.getByText(/原始 Skill/).closest("details")).not.toHaveAttribute("open");
  });
  it("resumes a queued run after refresh without submitting again", async () => {
    class ResumeApi extends CompletedTechnicalApi {
      override getTechnicalReportRun(): Promise<TechnicalRun> { return Promise.resolve(queuedRun); }
      override startTechnicalReportRun = vi.fn(() => Promise.resolve(queuedRun));
    }
    const api = new ResumeApi();
    renderPages(api, `/technical-reports?symbol=BTCUSDT&runId=${queuedRun.id}`);
    expect(await screen.findByText("等待开始")).toBeInTheDocument();
    expect(api.startTechnicalReportRun).not.toHaveBeenCalled();
    expect(screen.getByRole("button", {name: "生成技术报告"})).toBeDisabled();
  });

  it("query failure does not start another paid generation", async () => {
    class FailedQueryApi extends CompletedTechnicalApi {
      override getTechnicalReportRun(): Promise<TechnicalRun> { return Promise.reject(new Error("offline")); }
      override startTechnicalReportRun = vi.fn(() => Promise.resolve(queuedRun));
    }
    const api = new FailedQueryApi();
    renderPages(api, `/technical-reports?symbol=BTCUSDT&runId=${queuedRun.id}`);
    expect(await screen.findByRole("button", {name: "重试查询"})).toBeInTheDocument();
    expect(api.startTechnicalReportRun).not.toHaveBeenCalled();
  });
  it("renders conditional breakout plans with frozen facts and method attribution", async () => {
    renderPages(new CompletedTechnicalApi(), `/technical-reports/${completed.id}`);
    expect((await screen.findAllByText("70,000", { exact: false })).length).toBeGreaterThan(0);
    expect(screen.getByText(/后续.*1小时.*收盘/)).toBeInTheDocument();
    expect(screen.getByText(/1\.5/)).toBeInTheDocument();
    expect(screen.getByText(/原始 Skill/)).toBeInTheDocument();
    expect(screen.getByText(/量价结构偏强/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /下单|开仓/ })).not.toBeInTheDocument();
    expect(screen.getByText("已到期，请重新研究")).toBeInTheDocument();
  });

  it("keeps archived history readable while blocking new generation", async () => {
    renderPages(new CompletedTechnicalApi(), "/technical-reports?symbol=OLDUSDT");
    expect(await screen.findByText(/归档或未在当前研究目录/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /生成技术报告/ })).not.toBeInTheDocument();
  });

  it("lists existing history when no symbols remain available for new research", async () => {
    class ArchivedCatalogApi extends CompletedTechnicalApi {
      override listResearchSymbols() { return Promise.resolve([]); }
    }
    renderPages(new ArchivedCatalogApi(), "/technical-reports");
    expect(await screen.findByRole("link", { name: "查看技术报告" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "生成技术报告" })).not.toBeInTheDocument();
  });

  it("distinguishes registered pending symbols from archived symbols", async () => {
    class PendingCatalogApi extends CompletedTechnicalApi {
      override async listResearchSymbols() {
        return (await super.listResearchSymbols()).map((entry) => ({ ...entry, canResearch: false }));
      }
    }
    renderPages(new PendingCatalogApi(), "/technical-reports?symbol=BTCUSDT");
    expect(await screen.findByText(/数据尚未就绪/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "生成技术报告" })).not.toBeInTheDocument();
  });

  it("marks Mock generation as demo and navigates to its degraded detail", async () => {
    renderPages(new MockWorkbenchApi(), "/technical-reports?symbol=BTCUSDT");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "生成技术报告" }));
    expect(await screen.findByRole("link", { name: "返回历史报告" })).toBeInTheDocument();
    expect(screen.getAllByText(/演示数据/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/模型叙事不可用/).length).toBeGreaterThan(0);
    const headings = screen.getAllByRole("heading").map((heading) => heading.textContent);
    expect(headings.indexOf("等待与重新评估")).toBeLessThan(headings.indexOf("条件研究计划"));
    expect(headings.indexOf("条件研究计划")).toBeLessThan(headings.indexOf("报告与数据质量"));
  });

  it("does not navigate when generation for a former symbol resolves late", async () => {
    let resolveRun: ((report: TechnicalReport) => void) | undefined;
    class PendingApi extends MockWorkbenchApi {
      override startTechnicalReport(): Promise<TechnicalReport> {
        return new Promise((resolve) => { resolveRun = resolve; });
      }
    }
    renderPages(new PendingApi(), "/technical-reports?symbol=BTCUSDT");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "生成技术报告" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "研究币对" }), "ETHUSDT");
    resolveRun?.(completed);
    await waitFor(() => expect(window.location.pathname).toBe("/technical-reports"));
    expect(window.location.search).toContain("ETHUSDT");
  });
});
