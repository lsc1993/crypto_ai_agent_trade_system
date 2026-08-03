from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.market.contracts import ContractSymbol


class IntentAction(StrEnum):
    OPEN_LONG = "open_long"
    CLOSE_LONG = "close_long"


class TradeIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    symbol: ContractSymbol
    action: IntentAction
    decision_at: datetime
    strategy_id: Literal["sma_crossover"]
    strategy_version: Literal["v1"]
    idempotency_key: str

    @field_validator("decision_at")
    @classmethod
    def validate_decision_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("决策时间必须是 UTC 且带时区")
        return value
