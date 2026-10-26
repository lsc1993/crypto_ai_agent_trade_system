# 资金费率历史契约：结算时间与有限 Decimal 费率组成升序、去重且落在请求窗口内的研究序列。
# 公开行情领域：统一研究行情模型、固定公开来源适配器与冻结快照读取；不访问私有账户。
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.market.symbols import ResearchSymbol


# 资金费率契约的冻结公共基类，禁止额外字段。
class _FundingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# 一次已结算费率观察，时间必须为 UTC，费率允许负值但必须有限。
class FundingPoint(_FundingModel):
    funding_time: datetime
    funding_rate: Decimal

    # 校验funding_time 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：资金费率时间必须是 UTC 且带时区。
    @field_validator("funding_time")
    @classmethod
    def validate_funding_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("资金费率时间必须是 UTC 且带时区")
        return value

    # 校验funding_rate 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：资金费率必须是 Decimal 或十进制字符串；资金费率必须是有限十进制数；
    # 资金费率必须是有效十进制数。
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


# 指定研究标的和窗口的费率序列，验证时间升序、去重、窗口范围与抓取时序。
class FundingHistory(_FundingModel):
    symbol: ResearchSymbol
    since: datetime
    until: datetime
    fetched_at: datetime
    points: tuple[FundingPoint, ...]

    # 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
    @field_validator("since", "until", "fetched_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("资金费率历史时间必须是 UTC 且带时区")
        return value

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：资金费率历史开始时间必须早于结束时间；资金费率历史必须按时间升序且不能重复；
    # 资金费率历史包含窗口外时间。
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
