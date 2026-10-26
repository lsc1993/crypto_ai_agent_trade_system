# 行情网关协议：应用服务通过公开行情和历史 K 线接口读取标准模型，具体网络实现留在适配器。
# 公开行情领域：统一研究行情模型、固定公开来源适配器与冻结快照读取；不访问私有账户。
from datetime import datetime
from typing import Any, Protocol

from app.market.contracts import (
    Candle,
    ContractSymbol,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)


# PublicMarketGateway 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class PublicMarketGateway(Protocol):
    # 按传入标的范围读取标准化行情摘要并返回元组，具体数据来源由网关决定。
    async def get_summaries(
        self,
        symbols: tuple[Any, ...],
    ) -> tuple[MarketSummary, ...]: ...

    # 读取指定研究标的及周期的行情详情；返回摘要与各周期 K 线。
    async def get_market(
        self,
        symbol: Any,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail: ...


# HistoricalCandleGateway 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class HistoricalCandleGateway(Protocol):
    # 按静态标的、周期与请求时间区间读取已收盘历史 K 线，供确定性回放使用。
    async def load_closed_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[Candle, ...]: ...
