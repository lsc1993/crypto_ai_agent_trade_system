import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

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
  it("renders conditional breakout plans with frozen facts and method attribution", async () => {
    renderPages(new CompletedTechnicalApi(), `/technical-reports/${completed.id}`);
    expect((await screen.findAllByText("70,000", { exact: false })).length).toBeGreaterThan(0);
    expect(screen.getByText(/后续.*1h.*收盘/)).toBeInTheDocument();
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
