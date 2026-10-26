# 交易意图契约：记录运行、方向、UTC 决策时刻、来源和幂等键；策略来源须带版本，
# 手工与风险来源不得伪造策略元数据。
# 确定性策略领域：只从历史行情生成结构化交易意图，数量与成交由风控和模拟执行决定。
from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.market.contracts import ContractSymbol


# IntentAction 固定可用枚举值：OPEN_LONG、CLOSE_LONG；外部数据不能自行增加状态或动作。
class IntentAction(StrEnum):
    OPEN_LONG = "open_long"
    CLOSE_LONG = "close_long"


# IntentSource 固定可用枚举值：STRATEGY、MANUAL、RISK；外部数据不能自行增加状态或动作。
class IntentSource(StrEnum):
    STRATEGY = "strategy"
    MANUAL = "manual"
    RISK = "risk"


# 交易意图描述动作、来源和运行身份，保留版本与幂等键；数量和最终放行属于风控。
class TradeIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    symbol: ContractSymbol
    action: IntentAction
    decision_at: datetime
    source: IntentSource = IntentSource.STRATEGY
    strategy_id: str | None = None
    strategy_version: str | None = None
    idempotency_key: str

    # 校验decision_at 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：决策时间必须是 UTC 且带时区。
    @field_validator("decision_at")
    @classmethod
    def validate_decision_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("决策时间必须是 UTC 且带时区")
        return value

    # 校验strategy_id、strategy_version 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：策略元数据不能为空。
    @field_validator("strategy_id", "strategy_version")
    @classmethod
    def validate_strategy_metadata(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("策略元数据不能为空")
        return normalized

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：手动或风控意图不得包含策略元数据；策略意图必须包含策略标识和版本。
    @model_validator(mode="after")
    def validate_source_metadata(self) -> TradeIntent:
        has_strategy_metadata = self.strategy_id is not None or self.strategy_version is not None
        if self.source is IntentSource.STRATEGY:
            if self.strategy_id is None or self.strategy_version is None:
                raise ValueError("策略意图必须包含策略标识和版本")
            return self
        if has_strategy_metadata:
            raise ValueError("手动或风控意图不得包含策略元数据")
        return self
