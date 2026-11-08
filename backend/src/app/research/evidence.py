# 定义只读研究证据 epoch：共同分析截止口径、逐项来源/时间/质量和内容引用。
# 该模块是纯研究契约，不读取公开源、不冻结数据库、不依赖 Agent 图或交易执行。
# 证据封存后不得改写；市场详情只用于确定性评估，刷新当前数据不能冒充旧时点证据。
from __future__ import annotations

import copy
import json
from datetime import datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError, field_validator, model_validator

from app.market.contracts import MarketDetail
from app.shared.agent_types import (
    AgentModel,
    ArtifactRef,
    JsonObject,
    UtcDateTime,
    is_sha256,
    require_utc,
    sha256_json,
)

MARKET_EVIDENCE_KIND = "market_detail"
_MAX_CONTENT_BYTES = 4 * 1024 * 1024


# 证据不可用错误携带稳定原因码；调用方据此返回安全的无计划状态。
class EvidenceUnavailableError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# 证据质量分开表达完整、部分、过期、无效和缺失；未知不能当作可用。
class EvidenceQuality(StrEnum):
    VALID = "valid"
    PARTIAL = "partial"
    STALE = "stale"
    INVALID = "invalid"
    MISSING = "missing"


# 单条冻结证据：来源、观测/首次可得/抓取时间、内容指纹、质量和可选内容。
# content 只提供给本地确定性评估；content_ref 用于后续持久化或大型载荷引用。
class EvidenceItem(AgentModel):
    evidence_id: UUID
    kind: str
    source: str
    observed_at: UtcDateTime
    available_at: UtcDateTime
    fetched_at: UtcDateTime
    payload_sha256: str
    quality: EvidenceQuality
    content: JsonObject | None = None
    content_ref: ArtifactRef | None = None

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if not value or len(value) > 64 or not value.replace("_", "").isalnum():
            raise ValueError("证据类别必须是稳定的短标识")
        return value

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 256:
            raise ValueError("证据来源必须有界且非空")
        return normalized

    @field_validator("quality")
    @classmethod
    def validate_quality(cls, value: EvidenceQuality) -> EvidenceQuality:
        if value is not EvidenceQuality.VALID and value not in {
            EvidenceQuality.PARTIAL,
            EvidenceQuality.STALE,
            EvidenceQuality.INVALID,
            EvidenceQuality.MISSING,
        }:
            raise ValueError("证据质量状态无效")
        return value

    @field_validator("payload_sha256")
    @classmethod
    def validate_payload_sha256(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("证据内容指纹必须是 64 位小写十六进制")
        return value

    @field_validator("observed_at", "available_at", "fetched_at")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        return require_utc(value)

    # 内容在证据模型边界深拷贝，避免调用方修改原 JSON 后影响已构造证据。
    @field_validator("content", mode="before")
    @classmethod
    def isolate_content(cls, value: object) -> object:
        return copy.deepcopy(value)

    @model_validator(mode="after")
    def validate_content_and_times(self) -> EvidenceItem:
        if not self.observed_at <= self.available_at <= self.fetched_at:
            raise ValueError("证据时间必须满足 observed <= available <= fetched")
        if self.content is not None:
            try:
                serialized = json.dumps(
                    self.content,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            except (TypeError, ValueError) as error:
                raise ValueError("证据内容必须是 JSON 安全值") from error
            if len(serialized) > _MAX_CONTENT_BYTES:
                raise ValueError("证据内容超过本地封存上限")
            if sha256_json(self.content) != self.payload_sha256:
                raise ValueError("证据内容指纹与内容不一致")
        if self.content_ref is not None and self.content_ref.sha256 != self.payload_sha256:
            raise ValueError("证据引用指纹与内容指纹不一致")
        if self.quality != EvidenceQuality.MISSING and (
            self.content is None and self.content_ref is None
        ):
            raise ValueError("非缺失证据必须提供内容或内容引用")
        return self


# 统一分析截止口径下的证据集合；epoch 指纹覆盖全部逐项时间和内容指纹。
class EvidenceEpoch(AgentModel):
    epoch_id: UUID
    analysis_as_of: UtcDateTime
    sealed_at: UtcDateTime
    items: tuple[EvidenceItem, ...]
    sha256: str

    @field_validator("analysis_as_of", "sealed_at")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("证据 epoch 指纹必须是 64 位小写十六进制")
        return value

    # epoch 构造时隔离逐项对象，后续修改原始 items 不能改写已封存集合。
    @field_validator("items", mode="before")
    @classmethod
    def isolate_items(cls, value: object) -> object:
        return copy.deepcopy(value)

    @model_validator(mode="after")
    def validate_epoch(self) -> EvidenceEpoch:
        if self.analysis_as_of > self.sealed_at:
            raise ValueError("分析截止时间不能晚于封存时间")
        identifiers = tuple(str(item.evidence_id) for item in self.items)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("证据标识不能重复")
        if identifiers != tuple(sorted(identifiers)):
            raise ValueError("证据项必须按标识稳定排序")
        for item in self.items:
            if item.observed_at > self.analysis_as_of:
                raise ValueError("证据观测时间不能晚于分析截止时间")
            if item.available_at > self.analysis_as_of:
                raise ValueError("证据首次可得时间不能晚于分析截止时间")
            if item.fetched_at > self.sealed_at:
                raise ValueError("证据抓取时间不能晚于封存时间")
        payload = _epoch_payload(self.analysis_as_of, self.sealed_at, self.items)
        expected_sha256 = sha256_json(payload)
        if self.sha256 != expected_sha256:
            raise ValueError("证据 epoch 指纹与内容不一致")
        if self.epoch_id != uuid5(NAMESPACE_URL, f"evidence-epoch:{expected_sha256}"):
            raise ValueError("证据 epoch 标识与内容不一致")
        return self

    # 封存一组证据并计算稳定标识；先深拷贝逐项内容，排序保证同一集合顺序无关。
    @classmethod
    def seal(
        cls,
        *,
        analysis_as_of: datetime,
        sealed_at: datetime,
        items: tuple[EvidenceItem, ...],
    ) -> EvidenceEpoch:
        isolated = tuple(_isolated_item(item) for item in items)
        ordered = tuple(sorted(isolated, key=lambda item: str(item.evidence_id)))
        payload = _epoch_payload(analysis_as_of, sealed_at, ordered)
        digest = sha256_json(payload)
        return cls(
            epoch_id=uuid5(NAMESPACE_URL, f"evidence-epoch:{digest}"),
            analysis_as_of=analysis_as_of,
            sealed_at=sealed_at,
            items=ordered,
            sha256=digest,
        )

    # 在消费入口创建隔离快照，重验逐项内容指纹、epoch 哈希和标识；失败明确拒绝。
    def validated_snapshot(self) -> EvidenceEpoch:
        try:
            isolated = tuple(_isolated_item(item) for item in self.items)
            snapshot = EvidenceEpoch.seal(
                analysis_as_of=self.analysis_as_of,
                sealed_at=self.sealed_at,
                items=isolated,
            )
        except EvidenceUnavailableError as error:
            raise EvidenceUnavailableError(
                "evidence_epoch_tampered", "证据快照内容与指纹不一致"
            ) from error
        except (ValidationError, TypeError, ValueError) as error:
            raise EvidenceUnavailableError(
                "evidence_epoch_tampered", "证据快照内容与指纹不一致"
            ) from error
        if snapshot.sha256 != self.sha256 or snapshot.epoch_id != self.epoch_id:
            raise EvidenceUnavailableError("evidence_epoch_tampered", "证据快照与封存标识不一致")
        return snapshot

    # 返回唯一的市场证据项；先重验整个 epoch，避免嵌套内容修改后沿用旧指纹。
    def market_evidence(self) -> EvidenceItem:
        self.validated_snapshot()
        return self._market_item()

    # 将冻结市场内容还原为已校验行情详情；内容缺失或结构无效时明确不可用。
    def market_detail(self) -> MarketDetail:
        snapshot = self.validated_snapshot()
        item = snapshot._market_item()
        if item.quality is not EvidenceQuality.VALID:
            raise EvidenceUnavailableError("market_evidence_not_valid", "市场证据质量不足")
        if item.content is None:
            raise EvidenceUnavailableError(
                "market_evidence_content_missing", "市场证据只有引用，无法本地评估"
            )
        try:
            return MarketDetail.model_validate(item.content)
        except ValidationError as error:
            raise EvidenceUnavailableError("market_evidence_invalid", "市场证据结构无效") from error

    # 仅从当前对象选择市场项；调用方先在公开入口完成完整性快照校验。
    def _market_item(self) -> EvidenceItem:
        matches = tuple(item for item in self.items if item.kind == MARKET_EVIDENCE_KIND)
        if not matches:
            raise EvidenceUnavailableError("market_evidence_missing", "缺少市场证据")
        if len(matches) != 1:
            raise EvidenceUnavailableError("duplicate_market_evidence", "市场证据不唯一")
        return matches[0]


# 深拷贝证据项并重新校验内容指纹；返回对象与调用方后续修改隔离。
def _isolated_item(item: EvidenceItem) -> EvidenceItem:
    try:
        payload = item.model_dump(mode="python", by_alias=False)
        payload["content"] = copy.deepcopy(item.content)
        return EvidenceItem.model_validate(payload)
    except (ValidationError, TypeError, ValueError, AttributeError) as error:
        raise EvidenceUnavailableError(
            "evidence_item_tampered", "证据内容与逐项指纹不一致"
        ) from error


# 构造 epoch 指纹载荷；逐项内容指纹已包含内容，不把大型正文重复嵌入 epoch 摘要。
def _epoch_payload(
    analysis_as_of: datetime,
    sealed_at: datetime,
    items: tuple[EvidenceItem, ...],
) -> JsonObject:
    return {
        "analysisAsOf": analysis_as_of.isoformat(),
        "sealedAt": sealed_at.isoformat(),
        "items": [
            {
                "evidenceId": str(item.evidence_id),
                "kind": item.kind,
                "source": item.source,
                "observedAt": item.observed_at.isoformat(),
                "availableAt": item.available_at.isoformat(),
                "fetchedAt": item.fetched_at.isoformat(),
                "payloadSha256": item.payload_sha256,
                "quality": item.quality,
                "hasContent": item.content is not None,
                "contentRef": (
                    None
                    if item.content_ref is None
                    else item.content_ref.model_dump(mode="json", by_alias=False)
                ),
            }
            for item in items
        ],
    }


__all__ = [
    "EvidenceEpoch",
    "EvidenceItem",
    "EvidenceQuality",
    "EvidenceUnavailableError",
    "MARKET_EVIDENCE_KIND",
]
