from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.market.contracts import ContractSymbol


class _FundingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FundingPoint(_FundingModel):
    funding_time: datetime
    funding_rate: Decimal

    @field_validator("funding_time")
    @classmethod
    def validate_funding_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("资金费率时间必须是 UTC 且带时区")
        return value

    @field_validator("funding_rate", mode="before")
    @classmethod
    def validate_funding_rate(cls, value: object) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (Decimal, str)):
            raise ValueError("资金费率必须是 Decimal 或十进制字符串")
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError) as error:
            raise ValueError("资金费率必须是有效十进制数") from error
        if not parsed.is_finite():
            raise ValueError("资金费率必须是有限十进制数")
        return parsed


class FundingHistory(_FundingModel):
    symbol: ContractSymbol
    since: datetime
    until: datetime
    fetched_at: datetime
    points: tuple[FundingPoint, ...]

    @field_validator("since", "until", "fetched_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("资金费率历史时间必须是 UTC 且带时区")
        return value

    @model_validator(mode="after")
    def validate_window_and_points(self) -> FundingHistory:
        if self.since >= self.until:
            raise ValueError("资金费率历史开始时间必须早于结束时间")
        times = tuple(point.funding_time for point in self.points)
        if times != tuple(sorted(times)) or len(times) != len(set(times)):
            raise ValueError("资金费率历史必须按时间升序且不能重复")
        if any(
            point.funding_time < self.since
            or point.funding_time > self.until
            or point.funding_time > self.fetched_at
            for point in self.points
        ):
            raise ValueError("资金费率历史包含窗口外时间")
        return self
