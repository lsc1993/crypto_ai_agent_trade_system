import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import { pageSchema } from "../../domain/primitives";
import {
  tradeFiltersSchema,
  tradeSchema,
  type TradeFilters as TradeFilterValues,
} from "../../domain/trade";
import { TradeFilters } from "./TradeFilters";
import { TradeTable } from "./TradeTable";

function oneQueryValue(
  params: URLSearchParams,
  key: string,
): string | undefined {
  const values = params.getAll(key);
  return values.length === 1 && values[0] !== ""
    ? values[0]
    : undefined;
}

function numberQueryValue(
  params: URLSearchParams,
  key: string,
): number | undefined {
  const value = oneQueryValue(params, key);
  return value === undefined ? undefined : Number(value);
}

function parseQueryFilters(params: URLSearchParams) {
  return tradeFiltersSchema.safeParse({
    symbol: oneQueryValue(params, "symbol"),
    direction: oneQueryValue(params, "direction"),
    horizon: oneQueryValue(params, "horizon"),
    status: oneQueryValue(params, "status"),
    label: oneQueryValue(params, "label"),
    from: oneQueryValue(params, "from"),
    to: oneQueryValue(params, "to"),
    page: numberQueryValue(params, "page"),
    pageSize: numberQueryValue(params, "pageSize"),
  });
}

interface TradeListContentProps {
  searchParams: URLSearchParams;
}

function TradeListContent({
  searchParams,
}: TradeListContentProps) {
  const api = useWorkbenchApi();
  const parsedQuery = useMemo(
    () => parseQueryFilters(searchParams),
    [searchParams],
  );
  const [appliedFilters, setAppliedFilters] =
    useState<TradeFilterValues | null>(
      parsedQuery.success ? parsedQuery.data : null,
    );
  const tradesQuery = useQuery({
    queryKey: ["trades", appliedFilters],
    enabled: parsedQuery.success && appliedFilters !== null,
    queryFn: async () => {
      if (appliedFilters === null) {
        throw new Error("Trade filters are unavailable");
      }
      const response = await api.listTrades(appliedFilters);
      return pageSchema(tradeSchema).parse(response);
    },
  });

  if (!parsedQuery.success || appliedFilters === null) {
    return (
      <PageState
        state="error"
        message="交易日志筛选条件无效，请检查后重试。"
      />
    );
  }

  if (tradesQuery.isPending) {
    return <PageState state="loading" />;
  }

  if (tradesQuery.isError) {
    return (
      <PageState
        state="error"
        message="无法读取交易日志，请稍后重试。"
      />
    );
  }

  return (
    <section className="research-page">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">模拟研究记录</p>
          <h1>交易日志</h1>
          <p>
            记录人工研究决策与复盘，不连接账户，也不提供任何交易执行能力。
          </p>
        </div>
        <Link className="primary-action" to="/trades/new">
          新增交易日志
        </Link>
      </header>
      <TradeFilters
        initialFilters={appliedFilters}
        onApply={setAppliedFilters}
      />
      {tradesQuery.data.items.length === 0 ? (
        <PageState
          state="empty"
          message="当前筛选条件下没有交易日志。"
        />
      ) : (
        <TradeTable trades={tradesQuery.data.items} />
      )}
    </section>
  );
}

export function TradeListPage() {
  const [searchParams] = useSearchParams();

  return (
    <TradeListContent
      key={searchParams.toString()}
      searchParams={searchParams}
    />
  );
}
