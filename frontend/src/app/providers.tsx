import { QueryClientProvider } from "@tanstack/react-query";
import {
  Component,
  Suspense,
  createContext,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { BrowserRouter } from "react-router-dom";

import { PageState } from "../components/common/PageState";
import type { WorkbenchApi } from "../shared/api/workbench-api";
import { createWorkbenchQueryClient } from "./query-client";

const WorkbenchApiContext = createContext<WorkbenchApi | null>(null);

// Hooks are intentionally colocated with the single provider-owned API context.
// eslint-disable-next-line react-refresh/only-export-components
export function useWorkbenchApi(): WorkbenchApi {
  const api = useContext(WorkbenchApiContext);
  if (api === null) {
    throw new Error("WorkbenchApi provider is missing");
  }
  return api;
}

interface GlobalErrorBoundaryProps {
  children: ReactNode;
}

interface GlobalErrorBoundaryState {
  failed: boolean;
}

class GlobalErrorBoundary extends Component<
  GlobalErrorBoundaryProps,
  GlobalErrorBoundaryState
> {
  state: GlobalErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): GlobalErrorBoundaryState {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <main id="main-content">
          <PageState
            state="error"
            message="工作台暂时无法显示，请刷新页面后重试。"
          />
        </main>
      );
    }
    return this.props.children;
  }
}

export interface AppProvidersProps {
  api: WorkbenchApi;
  children: ReactNode;
}

export function AppProviders({ api, children }: AppProvidersProps) {
  const [queryClient] = useState(createWorkbenchQueryClient);

  return (
    <GlobalErrorBoundary>
      <Suspense
        fallback={
          <main id="main-content">
            <PageState state="loading" />
          </main>
        }
      >
        <QueryClientProvider client={queryClient}>
          <WorkbenchApiContext.Provider value={api}>
            <BrowserRouter>{children}</BrowserRouter>
          </WorkbenchApiContext.Provider>
        </QueryClientProvider>
      </Suspense>
    </GlobalErrorBoundary>
  );
}
