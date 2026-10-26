# 定义行情展示响应及领域 K 线到前端字段的映射。
# 按别名输出时间与 OHLC 字段，DecimalValue 保留十进制序列化契约。
# 响应映射只改变展示结构；查询去重保留输入顺序并拒绝重复值。
from __future__ import annotations

from fastapi import HTTPException
from pydantic import AnyHttpUrl, BaseModel, ConfigDict

from app.market.contracts import (
    Candle,
    CandleSeries,
    DecimalValue,
    MarketSummary,
    MarketTimeframe,
    UtcDateTime,
)
from app.market.symbols import ResearchSymbol


# MarketSummaryListResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：items；完整契约以下方声明为准。
class MarketSummaryListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[MarketSummary, ...]


# MarketNewsItem 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：id、title、summary、source、source_url、published_at；完整契约以下方声明为准。
class MarketNewsItem(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda value: "".join(
            [
                value.split("_")[0],
                *(part.capitalize() for part in value.split("_")[1:]),
            ]
        ),
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    id: str
    title: str
    summary: str
    source: str
    source_url: AnyHttpUrl
    published_at: UtcDateTime
    fetched_at: UtcDateTime
    symbols: tuple[ResearchSymbol, ...]


# MarketCandleResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：symbol、timeframe、open_time、close_time、open、high；完整契约以下方声明为准。
class MarketCandleResponse(BaseModel):
    """K 线对外响应，保持前端既有时间与 OHLC 字段契约。"""

    model_config = ConfigDict(
        alias_generator=lambda value: "".join(
            [
                value.split("_")[0],
                *(part.capitalize() for part in value.split("_")[1:]),
            ]
        ),
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    symbol: ResearchSymbol
    timeframe: MarketTimeframe
    open_time: UtcDateTime
    close_time: UtcDateTime
    open: DecimalValue
    high: DecimalValue
    low: DecimalValue
    close: DecimalValue
    volume: DecimalValue

    # 将领域 open_at/close_at 与价格字段映射到前端 openTime/closeTime 和 OHLC 名称。
    @classmethod
    def from_candle(cls, candle: Candle) -> MarketCandleResponse:
        return cls(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            open_time=candle.open_at,
            close_time=candle.close_at,
            open=candle.open_price,
            high=candle.high_price,
            low=candle.low_price,
            close=candle.close_price,
            volume=candle.volume,
        )


# MarketCandleSeriesResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：timeframe、candles；完整契约以下方声明为准。
class MarketCandleSeriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeframe: MarketTimeframe
    candles: tuple[MarketCandleResponse, ...]

    # 保留领域周期及 K 线顺序，逐项应用展示映射，不重新筛选或计算指标。
    @classmethod
    def from_series(cls, series: CandleSeries) -> MarketCandleSeriesResponse:
        return cls(
            timeframe=series.timeframe,
            candles=tuple(
                MarketCandleResponse.from_candle(candle) for candle in series.candles
            ),
        )


# MarketDetailResponse 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：summary、series、news；完整契约以下方声明为准。
class MarketDetailResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: MarketSummary
    series: tuple[MarketCandleSeriesResponse, ...]
    news: tuple[MarketNewsItem, ...] = ()


# 保留查询输入顺序并转为 tuple；出现重复值即抛出 422，避免重复采集或重复响应。
def require_unique[T](values: list[T], label: str) -> tuple[T, ...]:
    result = tuple(values)
    if len(result) != len(set(result)):
        raise HTTPException(
            status_code=422,
            detail=f"{label} 不能重复",
        )
    return result
