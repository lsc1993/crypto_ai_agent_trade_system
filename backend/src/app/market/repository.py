# 采集与持久化契约：指标、快照草稿和批次经严格校验后提交；稳定 JSON 编码与哈希让冻结输入可核对。
# 公开行情领域：统一研究行情模型、固定公开来源适配器与冻结快照读取；不访问私有账户。
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.market.contracts import Candle
from app.market.symbols import ResearchSymbol

_MAX_SNAPSHOT_PAYLOAD_BYTES = 64 * 1024


# MetricType 固定可用枚举值：PRICE、FUNDING_RATE、OPEN_INTEREST、CHANGE_24H、VOLUME_24H；
# 外部数据不能自行增加状态或动作。
class MetricType(StrEnum):
    PRICE = "price"
    FUNDING_RATE = "funding_rate"
    OPEN_INTEREST = "open_interest"
    CHANGE_24H = "change_24h"
    VOLUME_24H = "volume_24h"


# 拒绝载荷中的浮点数，以稳定字段排序与紧凑格式编码 JSON，供大小限制和哈希共用。
def _json_bytes(payload: dict[str, JsonValue]) -> bytes:
    if _contains_float(payload):
        raise ValueError("快照载荷不允许浮点数")
    try:
        serialized = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("快照载荷必须是有效 JSON") from error
    return serialized.encode("utf-8")


# 递归检查列表和字典中的浮点值，防止嵌套载荷绕过十进制约束。
def _contains_float(value: JsonValue) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, list):
        return any(_contains_float(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    return False


# 计算已规范化快照载荷的稳定 SHA-256。
def snapshot_payload_sha256(payload: dict[str, JsonValue]) -> str:
    """计算已规范化快照载荷的稳定 SHA-256。"""
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


# 市场保存模型的冻结基类，拒绝额外字段。
class _PersistenceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
def _validate_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是 UTC 且带时区")
    return value.astimezone(UTC)


# 仅接受 Decimal 或十进制字符串，拒绝布尔值和非有限数值。
def _validate_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, str)):
        raise ValueError("指标值必须是 Decimal 或十进制字符串")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError("指标值必须是有效十进制数") from error
    if not parsed.is_finite():
        raise ValueError("指标值必须是有限十进制数")
    return parsed


# 按指标类型拆分的观察值，记录来源与时间；价格、成交量和未平仓量不得为负。
class DerivativeObservation(_PersistenceModel):
    symbol: ResearchSymbol
    metric_type: MetricType
    value: Decimal
    source: str
    observed_at: datetime
    fetched_at: datetime

    # 校验value 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: object) -> Decimal:
        return _validate_decimal(value)

    # 校验source 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：数据来源不能为空。
    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("数据来源不能为空")
        return normalized

    # 校验observed_at、fetched_at 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    @field_validator("observed_at", "fetched_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _validate_utc(value)

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：抓取时间不能早于观测时间；该指标不能为负数。
    @model_validator(mode="after")
    def validate_observation(self) -> DerivativeObservation:
        if self.fetched_at < self.observed_at:
            raise ValueError("抓取时间不能早于观测时间")
        if self.metric_type in {
            MetricType.PRICE,
            MetricType.OPEN_INTEREST,
            MetricType.VOLUME_24H,
        } and self.value < 0:
            raise ValueError("该指标不能为负数")
        return self


# 待保存的冻结载荷，携带版本、时间与哈希，校验大小限制及哈希内容一致性。
class MarketSnapshotDraft(_PersistenceModel):
    id: UUID = Field(default_factory=uuid4)
    symbol: ResearchSymbol
    source: str
    captured_at: datetime
    data_as_of: datetime
    data_version: str
    payload: dict[str, JsonValue]
    payload_sha256: str

    # 校验source 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：数据来源不能为空。
    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("数据来源不能为空")
        return normalized

    # 校验captured_at、data_as_of 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    @field_validator("captured_at", "data_as_of")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _validate_utc(value)

    # 校验data_version 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：快照数据版本必须是 market-v1。
    @field_validator("data_version")
    @classmethod
    def validate_data_version(cls, value: str) -> str:
        if value != "market-v1":
            raise ValueError("快照数据版本必须是 market-v1")
        return value

    # 校验payload 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：快照载荷不能超过 64 KiB。
    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if len(_json_bytes(value)) > _MAX_SNAPSHOT_PAYLOAD_BYTES:
            raise ValueError("快照载荷不能超过 64 KiB")
        return value

    # 校验payload_sha256 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：快照哈希必须是小写 SHA-256。
    @field_validator("payload_sha256")
    @classmethod
    def validate_hash_format(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("快照哈希必须是小写 SHA-256")
        return value

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：数据截止时间不能晚于快照时间；快照哈希与载荷不一致。
    @model_validator(mode="after")
    def validate_snapshot(self) -> MarketSnapshotDraft:
        if self.data_as_of > self.captured_at:
            raise ValueError("数据截止时间不能晚于快照时间")
        # 哈希格式合法还不足以证明内容对应；必须用当前规范化载荷重新计算并比对。
        if self.payload_sha256 != snapshot_payload_sha256(self.payload):
            raise ValueError("快照哈希与载荷不一致")
        return self


# 同一标的 K 线、五类唯一指标及快照组成的批次，跨模型核对标的和数据截止时刻。
class MarketCaptureBatch(_PersistenceModel):
    symbol: ResearchSymbol
    candles: tuple[Candle, ...]
    observations: tuple[DerivativeObservation, ...]
    snapshot: MarketSnapshotDraft

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：采集批次至少需要一根已收盘 K 线；K 线标的必须与采集批次一致；K
    # 线收盘时间不能晚于快照时间；快照标的必须与采集批次一致；观测标的必须与采集批次一致；
    # 采集批次必须包含五类唯一市场观测；快照数据截止时间必须等于最早观测时间。
    @model_validator(mode="after")
    def validate_capture_batch(self) -> MarketCaptureBatch:
        if not self.candles:
            raise ValueError("采集批次至少需要一根已收盘 K 线")
        if any(candle.symbol != self.symbol for candle in self.candles):
            raise ValueError("K 线标的必须与采集批次一致")
        if any(candle.close_at > self.snapshot.captured_at for candle in self.candles):
            raise ValueError("K 线收盘时间不能晚于快照时间")
        if self.snapshot.symbol != self.symbol:
            raise ValueError("快照标的必须与采集批次一致")
        if any(observation.symbol != self.symbol for observation in self.observations):
            raise ValueError("观测标的必须与采集批次一致")
        metric_types = {observation.metric_type for observation in self.observations}
        if len(self.observations) != len(MetricType) or metric_types != set(MetricType):
            raise ValueError("采集批次必须包含五类唯一市场观测")
        data_points = (
            *(candle.observed_at for candle in self.candles),
            *(observation.observed_at for observation in self.observations),
        )
        if self.snapshot.data_as_of != min(data_points):
            raise ValueError("快照数据截止时间必须等于最早观测时间")
        return self


# MarketRepository 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class MarketRepository(Protocol):
    # 保存一组完成校验的采集批次，返回对应快照标识。
    async def persist_batches(
        self,
        batches: tuple[MarketCaptureBatch, ...],
    ) -> tuple[UUID, ...]: ...
