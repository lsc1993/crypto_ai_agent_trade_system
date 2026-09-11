import type { Symbol } from "../../domain/primitives";
import type { ResearchSymbolEntry } from "../../domain/research-symbol";

export interface ResearchSymbolSelectProps {
  entries: ResearchSymbolEntry[];
  value: Symbol | undefined;
  pending: boolean;
  onValueChange: (symbol: Symbol) => void;
}

export function ResearchSymbolSelect({
  entries,
  value,
  pending,
  onValueChange,
}: ResearchSymbolSelectProps) {
  return (
    <label className="research-symbol-select">
      <span>研究币对</span>
      <select
        aria-label="研究币对"
        disabled={pending || entries.length === 0}
        value={value ?? ""}
        onChange={(event) => onValueChange(event.target.value)}
      >
        {value === undefined ? <option value="">正在加载币对</option> : null}
        {value !== undefined && !entries.some((entry) => entry.symbol === value) ? (
          <option value={value}>{value}</option>
        ) : null}
        {entries
          .filter((entry) => entry.canResearch)
          .map((entry) => (
            <option key={entry.symbol} value={entry.symbol}>
              {entry.symbol}
            </option>
          ))}
      </select>
    </label>
  );
}
