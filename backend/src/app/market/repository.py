from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.market.contracts import Candle, ContractSymbol

_MAX_SNAPSHOT_PAYLOAD_BYTES = 64 * 1024


class MetricType(StrEnum):
    PRICE = "price"
    FUNDING_RATE = "funding_rate"
    OPEN_INTEREST = "open_interest"
    CHANGE_24H = "change_24h"
    VOLUME_24H = "volume_24h"


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


def _contains_float(value: JsonValue) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, list):
        return any(_contains_float(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    return False


def snapshot_payload_sha256(payload: dict[str, JsonValue]) -> str:
    """计算已规范化快照载荷的稳定 SHA-256。"""
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


class _PersistenceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _validate_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是 UTC 且带时区")
    return value.astimezone(UTC)


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


class DerivativeObservation(_PersistenceModel):
    symbol: ContractSymbol
    metric_type: MetricType
    value: Decimal
    source: str
    observed_at: datetime
    fetched_at: datetime

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: object) -> Decimal:
        return _validate_decimal(value)

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("数据来源不能为空")
        return normalized

    @field_validator("observed_at", "fetched_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _validate_utc(value)

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


class MarketSnapshotDraft(_PersistenceModel):
    id: UUID = Field(default_factory=uuid4)
    symbol: ContractSymbol
    source: str
    captured_at: datetime
    data_as_of: datetime
    data_version: str
    payload: dict[str, JsonValue]
    payload_sha256: str

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("数据来源不能为空")
        return normalized

    @field_validator("captured_at", "data_as_of")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _validate_utc(value)

    @field_validator("data_version")
    @classmethod
    def validate_data_version(cls, value: str) -> str:
        if value != "market-v1":
            raise ValueError("快照数据版本必须是 market-v1")
        return value

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if len(_json_bytes(value)) > _MAX_SNAPSHOT_PAYLOAD_BYTES:
            raise ValueError("快照载荷不能超过 64 KiB")
        return value

    @field_validator("payload_sha256")
    @classmethod
    def validate_hash_format(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("快照哈希必须是小写 SHA-256")
        return value

    @model_validator(mode="after")
    def validate_snapshot(self) -> MarketSnapshotDraft:
        if self.data_as_of > self.captured_at:
            raise ValueError("数据截止时间不能晚于快照时间")
        if self.payload_sha256 != snapshot_payload_sha256(self.payload):
            raise ValueError("快照哈希与载荷不一致")
        return self


class MarketCaptureBatch(_PersistenceModel):
    symbol: ContractSymbol
    candles: tuple[Candle, ...]
    observations: tuple[DerivativeObservation, ...]
    snapshot: MarketSnapshotDraft

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


class MarketRepository(Protocol):
    async def persist_batches(
        self,
        batches: tuple[MarketCaptureBatch, ...],
    ) -> tuple[UUID, ...]: ...
