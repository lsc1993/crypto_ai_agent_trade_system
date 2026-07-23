export type PageStateKind =
  | "loading"
  | "empty"
  | "error"
  | "unavailable";

export interface PageStateProps {
  state: PageStateKind;
  message?: string;
}

const stateLabels: Record<PageStateKind, string> = {
  loading: "正在加载数据",
  empty: "暂无数据",
  error: "数据加载失败",
  unavailable: "数据暂不可用",
};

const stateDescriptions: Record<PageStateKind, string> = {
  loading: "请稍候，正在读取工作台数据。",
  empty: "当前筛选条件下没有可显示的数据。",
  error: "读取数据时发生错误，请稍后重试。",
  unavailable: "此数据能力尚未连接，请稍后再试。",
};

export function PageState({ state, message }: PageStateProps) {
  const role = state === "error" ? "alert" : "status";

  return (
    <section
      className={`page-state page-state--${state}`}
      role={role}
      aria-busy={state === "loading" ? "true" : undefined}
    >
      <h2 className="page-state__title">{stateLabels[state]}</h2>
      <p>{message ?? stateDescriptions[state]}</p>
    </section>
  );
}
