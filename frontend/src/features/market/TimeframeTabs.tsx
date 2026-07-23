import type { KeyboardEvent } from "react";

import type { Timeframe } from "../../domain/primitives";
import { MARKET_TIMEFRAMES } from "./market-timeframes";

export interface TimeframeTabsProps {
  value: Timeframe;
  onValueChange: (value: Timeframe) => void;
}

function adjacentTimeframe(
  value: Timeframe,
  direction: -1 | 1,
): Timeframe {
  const currentIndex = MARKET_TIMEFRAMES.indexOf(value);
  const nextIndex =
    (currentIndex + direction + MARKET_TIMEFRAMES.length) %
    MARKET_TIMEFRAMES.length;
  return MARKET_TIMEFRAMES[nextIndex] ?? value;
}

export function TimeframeTabs({
  value,
  onValueChange,
}: TimeframeTabsProps) {
  function selectFromKeyboard(
    event: KeyboardEvent<HTMLButtonElement>,
    timeframe: Timeframe,
  ) {
    let next: Timeframe | undefined;
    if (event.key === "ArrowRight") {
      next = adjacentTimeframe(timeframe, 1);
    } else if (event.key === "ArrowLeft") {
      next = adjacentTimeframe(timeframe, -1);
    } else if (event.key === "Home") {
      next = MARKET_TIMEFRAMES[0];
    } else if (event.key === "End") {
      next = MARKET_TIMEFRAMES[MARKET_TIMEFRAMES.length - 1];
    }
    if (next === undefined) {
      return;
    }

    event.preventDefault();
    onValueChange(next);
    event.currentTarget.parentElement
      ?.querySelector<HTMLButtonElement>(
        `[data-timeframe="${next}"]`,
      )
      ?.focus();
  }

  return (
    <div
      className="timeframe-tabs"
      role="tablist"
      aria-label="K 线周期"
    >
      {MARKET_TIMEFRAMES.map((timeframe) => (
        <button
          className="timeframe-tabs__tab"
          type="button"
          role="tab"
          aria-selected={value === timeframe}
          aria-controls="market-timeframe-panel"
          id={`market-timeframe-tab-${timeframe}`}
          tabIndex={value === timeframe ? 0 : -1}
          data-timeframe={timeframe}
          key={timeframe}
          onClick={() => {
            onValueChange(timeframe);
          }}
          onKeyDown={(event) => {
            selectFromKeyboard(event, timeframe);
          }}
        >
          {timeframe}
        </button>
      ))}
    </div>
  );
}
