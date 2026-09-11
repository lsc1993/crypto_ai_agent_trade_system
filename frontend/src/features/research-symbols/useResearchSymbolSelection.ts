import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { useWorkbenchApi } from "../../app/providers";
import type { Symbol } from "../../domain/primitives";

const SELECTED_RESEARCH_SYMBOL_KEY = "crypto-ai:selected-research-symbol";

export function rememberResearchSymbol(symbol: Symbol): void {
  localStorage.setItem(SELECTED_RESEARCH_SYMBOL_KEY, symbol);
}

function rememberedResearchSymbol(): string | null {
  return localStorage.getItem(SELECTED_RESEARCH_SYMBOL_KEY);
}

export function useResearchSymbolSelection(options?: { pathSymbol?: string | undefined }) {
  const api = useWorkbenchApi();
  const [searchParams, setSearchParams] = useSearchParams();
  const catalogQuery = useQuery({
    queryKey: ["research-symbols"],
    queryFn: () => api.listResearchSymbols(),
  });
  const requested =
    options?.pathSymbol ??
    searchParams.get("symbol") ??
    rememberedResearchSymbol();
  const entries = catalogQuery.data ?? [];
  const matched = entries.find(
    (entry) => entry.symbol === requested && entry.canResearch,
  );
  const selected =
    matched?.symbol ??
    (catalogQuery.isPending && requested != null ? requested : undefined) ??
    entries.find((entry) => entry.canResearch)?.symbol;
  const invalid =
    catalogQuery.isSuccess &&
    requested !== null &&
    requested !== undefined &&
    !entries.some((entry) => entry.symbol === requested && entry.canResearch);

  function select(symbol: Symbol): void {
    rememberResearchSymbol(symbol);
    const next = new URLSearchParams(searchParams);
    next.set("symbol", symbol);
    setSearchParams(next, { replace: true });
  }

  return {
    catalogQuery,
    entries,
    selected,
    invalid,
    select,
  };
}
