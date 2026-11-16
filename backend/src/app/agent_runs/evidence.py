# 定义 C5 的冻结证据服务：通过注入的受治理公开证据端口采集、封存并持久化 EvidenceEpoch。
# 服务只处理公开研究证据，不读取私有账户、不调用模型/工具、不生成交易请求或财务值。
# 初始公开读取按传输预算逐次预留/发送/结算；外部结果未知时保守占用，不伪造成功。
from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, JsonValue, field_validator, model_validator

from app.agent_runs.attempts import (
    AttemptCategory,
    AttemptRequest,
    AttemptResult,
    AttemptStatus,
    StepAttempt,
)
from app.agent_runs.budget import BudgetLedger
from app.agent_runs.contracts import AgentRunError, RunSnapshot, RunStatus
from app.agent_runs.ports import AgentRunReader
from app.agent_runs.segments import ExecutionContext, RunFence
from app.market.contracts import MarketTimeframe
from app.research.evidence import (
    EvidenceEpoch,
    EvidenceItem,
    EvidenceQuality,
    EvidenceUnavailableError,
)
from app.shared.agent_types import (
    AgentModel,
    ArtifactRef,
    JsonObject,
    ProductKey,
    UtcDateTime,
    is_sha256,
    require_utc,
    sha256_json,
)

# 初始证据读取使用独立的高序号区段，避免与模型/工具动作的低序号步骤冲突。
# 每次刷新再按已保存 epoch 数推进一个区段；SQL 唯一约束仍按 run/revision/action_sequence。
EVIDENCE_ACTION_SEQUENCE_BASE = 1_000_000
# 公开行情最坏扇出：3 个摘要端点 + 4 个周期端点，各最多 2 次尝试 = 14；留出 16 的硬边界。
MAX_EVIDENCE_TRANSPORT_CALLS = 16
MAX_EVIDENCE_ITEMS = 8
_MAX_EVIDENCE_CONTENT_BYTES = 4 * 1024 * 1024
_SAFE_VERSION = re.compile(r"[a-z0-9_]{1,64}\Z")
_SAFE_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


# 公开证据端口只接收服务端解析后的产品/周期/截止时间；不接受模型传入 URL、SQL 或代码。
class ResearchEvidencePort(Protocol):
    def planned_transport_calls(self, timeframes: tuple[MarketTimeframe, ...]) -> int: ...

    async def collect(
        self,
        *,
        product: ProductKey,
        timeframes: tuple[MarketTimeframe, ...],
        analysis_as_of: datetime,
    ) -> EvidenceCollection: ...


# 证据事实投影端口：把已封存的公开证据转换为模型可见的有界事实文本。
# 投影器不能读取私有财务表单，也不能把外部文本升级为系统指令。
class EvidenceFactProjector(Protocol):
    def project(self, item: EvidenceItem) -> str | None: ...


# 证据持久化端口；SQL 实现负责围栏、工作台隔离和不可变触发器。
class EvidenceRepository(Protocol):
    async def save_evidence(self, fence: RunFence, epoch: EvidenceEpoch) -> EvidenceEpoch: ...

    async def load_evidence(
        self,
        workspace_id: UUID,
        run_id: UUID,
        epoch_id: UUID,
    ) -> EvidenceEpoch | None: ...

    async def load_latest_evidence(
        self,
        workspace_id: UUID,
        run_id: UUID,
        revision: int,
    ) -> EvidenceEpoch | None: ...

    async def count_evidence(
        self,
        workspace_id: UUID,
        run_id: UUID,
        revision: int,
    ) -> int: ...


# 单条待封存证据；时间、来源、质量和计算版本先由端口声明，再由服务做边界校验。
# payload_sha256 为空时由 content 计算；只有 content_ref 时必须显式提供并以引用指纹为准。
class EvidenceDraft(AgentModel):
    kind: str
    source: str
    observed_at: UtcDateTime
    available_at: UtcDateTime
    fetched_at: UtcDateTime
    quality: EvidenceQuality = EvidenceQuality.VALID
    calculation_version: str | None = None
    content: JsonObject | None = None
    content_ref: ArtifactRef | None = None
    payload_sha256: str | None = None

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

    @field_validator("observed_at", "available_at", "fetched_at")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("calculation_version")
    @classmethod
    def validate_calculation_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _SAFE_VERSION.fullmatch(value) is None:
            raise ValueError("证据计算版本必须是稳定短标识")
        return value

    # 草稿内容在模型边界深拷贝并校验 JSON 安全/大小；调用方后续修改原对象不能改写封存输入。
    @field_validator("content", mode="before")
    @classmethod
    def isolate_content(cls, value: object) -> object:
        return copy.deepcopy(value)

    @model_validator(mode="after")
    def validate_draft(self) -> EvidenceDraft:
        if not self.observed_at <= self.available_at <= self.fetched_at:
            raise ValueError("证据时间必须满足 observed <= available <= fetched")
        if self.content is None and self.content_ref is not None and self.payload_sha256 is None:
            raise ValueError("仅有内容引用时必须提供内容指纹")
        expected = self.expected_payload_sha256()
        if self.payload_sha256 is not None:
            if not is_sha256(self.payload_sha256):
                raise ValueError("证据内容指纹必须是 64 位小写十六进制")
            if self.payload_sha256 != expected:
                raise ValueError("证据内容指纹与内容不一致")
        if self.content_ref is not None and self.content_ref.sha256 != expected:
            raise ValueError("证据引用指纹与内容指纹不一致")
        if self.quality is not EvidenceQuality.MISSING and (
            self.content is None and self.content_ref is None
        ):
            raise ValueError("非缺失证据必须提供内容或内容引用")
        return self

    # 计算草稿预期内容指纹；MISSING 且无内容时使用全零占位，不能把缺失当真实内容。
    def expected_payload_sha256(self) -> str:
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
            if len(serialized) > _MAX_EVIDENCE_CONTENT_BYTES:
                raise ValueError("证据内容超过本地封存上限")
            return sha256_json(cast(JsonValue, self.content))
        if self.payload_sha256 is not None:
            return self.payload_sha256
        return "0" * 64

    # 构造不可变 EvidenceItem；标识由内容/来源/时间/版本稳定派生，重复内容不会得到第二个 ID。
    def to_item(self) -> EvidenceItem:
        payload_sha256 = self.expected_payload_sha256()
        identity: JsonObject = {
            "kind": self.kind,
            "source": self.source,
            "observedAt": self.observed_at.isoformat(),
            "availableAt": self.available_at.isoformat(),
            "fetchedAt": self.fetched_at.isoformat(),
            "payloadSha256": payload_sha256,
            "calculationVersion": self.calculation_version,
            "contentRef": (
                None
                if self.content_ref is None
                else self.content_ref.model_dump(mode="json", by_alias=False)
            ),
        }
        evidence_id = uuid5(
            NAMESPACE_URL,
            f"evidence-item:{sha256_json(identity)}",
        )
        return EvidenceItem(
            evidence_id=evidence_id,
            kind=self.kind,
            source=self.source,
            observed_at=self.observed_at,
            available_at=self.available_at,
            fetched_at=self.fetched_at,
            payload_sha256=payload_sha256,
            quality=self.quality,
            calculation_version=self.calculation_version,
            content=copy.deepcopy(self.content),
            content_ref=self.content_ref,
        )


# 一次公开证据读取返回的草稿集合；服务统一分配 epoch 时间和持久化引用。
class EvidenceCollection(AgentModel):
    items: tuple[EvidenceDraft, ...] = Field(min_length=1, max_length=MAX_EVIDENCE_ITEMS)

    @field_validator("items", mode="before")
    @classmethod
    def isolate_items(cls, value: object) -> object:
        return copy.deepcopy(value)


# 冻结服务：先认领当前运行/围栏，再按计划传输次数预留预算，最后封存并保存证据。
# 已保存 epoch 默认复用；显式 refresh 才重新读取，且必须进入新的动作序号区段。
class EvidenceService:
    def __init__(
        self,
        *,
        run_reader: AgentRunReader,
        evidence_port: ResearchEvidencePort,
        repository: EvidenceRepository,
        budget: BudgetLedger,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._runs = run_reader
        self._port = evidence_port
        self._repository = repository
        self._budget = budget
        self._clock = clock or (lambda: datetime.now(UTC))

    async def freeze(
        self,
        context: ExecutionContext,
        *,
        refresh: bool = False,
    ) -> EvidenceEpoch:
        # 只有非刷新调用复用已绑定 epoch；显式刷新必须重新检查运行、预算和公开源。
        if context.evidence_epoch is not None and not refresh:
            stored = await self._repository.load_latest_evidence(
                context.fence.workspace_id,
                context.fence.run_id,
                context.fence.revision,
            )
            if (
                stored is None
                or stored.epoch_id != context.evidence_epoch.epoch_id
                or stored.sha256 != context.evidence_epoch.sha256
            ):
                raise AgentRunError("run_state_conflict")
            return context.evidence_epoch.validated_snapshot()
        snapshot = await self._runs.get(
            context.fence.workspace_id,
            context.fence.run_id,
        )
        self._validate_snapshot(context.fence, snapshot)
        assert snapshot is not None

        if snapshot.input.analysis_mode != "current":
            raise EvidenceUnavailableError(
                "historical_evidence_unavailable",
                "当前公开证据端口不能证明历史可得时间，拒绝历史模式",
            )

        if not refresh:
            existing = await self._repository.load_latest_evidence(
                context.fence.workspace_id,
                context.fence.run_id,
                context.fence.revision,
            )
            if existing is not None:
                return existing.validated_snapshot()

        planned = self._port.planned_transport_calls(snapshot.input.timeframes)
        if not 1 <= planned <= MAX_EVIDENCE_TRANSPORT_CALLS:
            raise EvidenceUnavailableError(
                "evidence_transport_plan_invalid",
                "公开证据读取计划超出传输预算边界",
            )

        evidence_count = await self._repository.count_evidence(
            context.fence.workspace_id,
            context.fence.run_id,
            context.fence.revision,
        )
        sequence_base = EVIDENCE_ACTION_SEQUENCE_BASE + (
            evidence_count * MAX_EVIDENCE_TRANSPORT_CALLS
        )
        input_sha256 = sha256_json(
            cast(
                JsonValue,
                {
                    "purpose": "initial_evidence",
                    "runId": str(context.fence.run_id),
                    "revision": context.fence.revision,
                    "product": snapshot.input.product.model_dump(mode="json", by_alias=False),
                    "timeframes": [item.value for item in snapshot.input.timeframes],
                    "collection": evidence_count,
                },
            )
        )
        attempts: list[StepAttempt] = []
        try:
            for index in range(planned):
                attempts.append(
                    await self._budget.reserve(
                        context.fence,
                        AttemptRequest(
                            action_sequence=sequence_base + index,
                            input_sha256=input_sha256,
                            category=AttemptCategory.TRANSPORT,
                        ),
                    )
                )
        except Exception:
            # 预算不足或存储失败时，已预留但未发送的传输必须按发送前失败释放。
            await self._settle_quietly(
                context.fence,
                attempts,
                AttemptStatus.FAILED,
                reason_code="evidence_not_sent",
            )
            raise

        sent: list[StepAttempt] = []
        try:
            for attempt in attempts:
                await self._budget.mark_sent(context.fence, attempt.attempt_id)
                sent.append(attempt)
        except Exception:
            await self._settle_quietly(
                context.fence,
                sent,
                AttemptStatus.FAILED,
                reason_code="evidence_send_failed",
            )
            await self._settle_quietly(
                context.fence,
                [item for item in attempts if item.attempt_id not in {x.attempt_id for x in sent}],
                AttemptStatus.FAILED,
                reason_code="evidence_not_sent",
            )
            raise

        # 读取前先取截止候选，供端口拒绝截止后收盘的 K 线；读取完成后再取封存时刻，
        # 避免把正常发生在读取之后的 fetched_at 误判为“未来证据”。
        requested_at = require_utc(self._clock())
        try:
            collection = await self._port.collect(
                product=snapshot.input.product,
                timeframes=snapshot.input.timeframes,
                analysis_as_of=requested_at,
            )
        except Exception:
            # 外部读取异常可能发生在请求已发出之后；按 unknown 保留最坏预算，不保存半成品。
            await self._settle_quietly(
                context.fence,
                sent,
                AttemptStatus.UNKNOWN,
                reason_code="evidence_outcome_unknown",
            )
            raise EvidenceUnavailableError(
                "evidence_collection_failed",
                "公开证据读取失败或结果未知",
            ) from None

        sealed_at = require_utc(self._clock())
        if sealed_at < requested_at:
            await self._settle_quietly(
                context.fence,
                sent,
                AttemptStatus.FAILED,
                reason_code="evidence_clock_regression",
            )
            raise EvidenceUnavailableError(
                "evidence_clock_regression",
                "封存时钟早于读取请求时刻",
            )
        try:
            epoch = self._seal(collection, now=sealed_at)
        except EvidenceUnavailableError as error:
            await self._settle_quietly(
                context.fence,
                sent,
                AttemptStatus.FAILED,
                reason_code=error.code,
            )
            raise
        except (TypeError, ValueError):
            await self._settle_quietly(
                context.fence,
                sent,
                AttemptStatus.FAILED,
                reason_code="evidence_invalid",
            )
            raise EvidenceUnavailableError(
                "evidence_invalid",
                "公开证据未通过密封校验",
            ) from None

        try:
            saved = await self._repository.save_evidence(context.fence, epoch)
        except Exception:
            # 读取已完成但持久化失败：外部成本已可能发生，按 unknown 保留预算占用。
            await self._settle_quietly(
                context.fence,
                sent,
                AttemptStatus.UNKNOWN,
                reason_code="evidence_persist_failed",
            )
            raise

        reference = ArtifactRef(artifact_id=saved.epoch_id, sha256=saved.sha256)
        settle_error: Exception | None = None
        for attempt in sent:
            try:
                await self._budget.settle(
                    context.fence,
                    attempt.attempt_id,
                    AttemptResult(
                        status=AttemptStatus.SUCCEEDED,
                        result_ref=reference,
                    ),
                )
            except Exception as error:
                # 证据已保存，不能因单个结算失败丢掉已封存结果；尽量结算其余尝试，
                # 最终把错误交给 worker，由恢复/对账处理剩余 in_flight。
                settle_error = settle_error or error
        if settle_error is not None:
            raise settle_error
        return saved.validated_snapshot()

    # 当前 owner/代次/修订/状态必须与快照一致；取消标记优先阻止新公开调用。
    @staticmethod
    def _validate_snapshot(fence: RunFence, snapshot: RunSnapshot | None) -> None:
        if snapshot is None:
            raise AgentRunError("run_not_found")
        if snapshot.revision != fence.revision:
            raise AgentRunError("lease_lost")
        if snapshot.status is not RunStatus.RUNNING:
            raise AgentRunError("lease_lost")
        if snapshot.cancel_requested_at is not None:
            raise AgentRunError("run_cancelling")

    # 统一封存入口：拒绝未来时间/重复项，并让 EvidenceEpoch 重新计算稳定标识。
    @staticmethod
    def _seal(collection: EvidenceCollection, *, now: datetime) -> EvidenceEpoch:
        items: list[EvidenceItem] = []
        for draft in collection.items:
            if draft.observed_at > now or draft.available_at > now or draft.fetched_at > now:
                raise EvidenceUnavailableError(
                    "evidence_time_in_future",
                    "证据观测/可得/抓取时间不能晚于服务端封存时刻",
                )
            items.append(draft.to_item())
        return EvidenceEpoch.seal(
            analysis_as_of=now,
            sealed_at=now,
            items=tuple(items),
        )

    # 结算清理失败不能掩盖原始错误；调用方会保留未结算占用并让恢复器处理。
    async def _settle_quietly(
        self,
        fence: RunFence,
        attempts: list[StepAttempt],
        status: AttemptStatus,
        *,
        reason_code: str,
    ) -> None:
        if _SAFE_REASON.fullmatch(reason_code) is None:
            raise ValueError("证据结算原因必须是稳定短码")
        for attempt in attempts:
            with suppress(Exception):
                await self._budget.settle(
                    fence,
                    attempt.attempt_id,
                    AttemptResult(status=status, reason_code=reason_code),
                )


__all__ = [
    "EVIDENCE_ACTION_SEQUENCE_BASE",
    "MAX_EVIDENCE_ITEMS",
    "MAX_EVIDENCE_TRANSPORT_CALLS",
    "EvidenceCollection",
    "EvidenceDraft",
    "EvidenceFactProjector",
    "EvidenceRepository",
    "EvidenceService",
    "ResearchEvidencePort",
]
