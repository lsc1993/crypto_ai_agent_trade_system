# 公开行情查询门面：将研究标的和周期传给注入网关，直接返回标准摘要或详情，不维护交易状态。
# 公开行情领域：统一研究行情模型、固定公开来源适配器与冻结快照读取；不访问私有账户。
from app.market.contracts import (
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.gateway import PublicMarketGateway
from app.market.symbols import ResearchSymbol


# 为 API 提供已标准化的只读公开市场数据。
class MarketQueryService:
    """为 API 提供已标准化的只读公开市场数据。"""

    # 初始化本实例依赖和配置；输入 gateway。
    def __init__(self, gateway: PublicMarketGateway) -> None:
        self._gateway = gateway

    # 按传入标的范围读取标准化行情摘要并返回元组，具体数据来源由网关决定。
    async def get_summaries(
        self,
        symbols: tuple[ResearchSymbol, ...],
    ) -> tuple[MarketSummary, ...]:
        return await self._gateway.get_summaries(symbols)

    # 读取指定研究标的及周期的行情详情；返回摘要与各周期 K 线。
    async def get_market(
        self,
        symbol: ResearchSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        return await self._gateway.get_market(symbol, timeframes)
