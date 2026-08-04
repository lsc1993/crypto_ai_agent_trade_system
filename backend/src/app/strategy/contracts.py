from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.market.contracts import ContractSymbol


class IntentAction(StrEnum):
    OPEN_LONG = "open_long"
    CLOSE_LONG = "close_long"


class IntentSource(StrEnum):
    STRATEGY = "strategy"
    MANUAL = "manual"
    RISK = "risk"


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

    @field_validator("decision_at")
    @classmethod
    def validate_decision_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("决策时间必须是 UTC 且带时区")
        return value

    @field_validator("strategy_id", "strategy_version")
    @classmethod
    def validate_strategy_metadata(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("策略元数据不能为空")
        return normalized

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
