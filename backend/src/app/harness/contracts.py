# 定义研究运行请求、白名单策略及工作流协议，将运行权限表达为有限能力集合。
# 研究目录准入只授权公开研究，不能扩大交易契约或授予私有账户与订单权限。
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.market.contracts import UtcDateTime
from app.market.symbols import ResearchSymbol


# 区分综合与独立技术研究，注册和审计均以运行类别为键。
class HarnessRunKind(StrEnum):
    MARKET_RESEARCH = "market_research"
    TECHNICAL_RESEARCH = "technical_research"


# 允许能力只有公开读取、受限模型和不可变保存；不能由输入扩展能力枚举。
class HarnessCapability(StrEnum):
    READ_PUBLIC_MARKET = "read_public_market"
    READ_APPROVED_NEWS = "read_approved_news"
    CALL_RESEARCH_MODEL = "call_research_model"
    PERSIST_IMMUTABLE_REPORT = "persist_immutable_report"


# 不可变手动请求携带关联标识、标的和 UTC 时间，不携带任意工具参数。
class HarnessRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    kind: HarnessRunKind
    symbol: ResearchSymbol
    requested_at: UtcDateTime

    @field_validator("requested_at")
    @classmethod
    def validate_utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("时间必须是 UTC 且带时区")
        return value.astimezone(UTC)


# 将运行类别、标的准入模式与能力白名单冻结为可审计策略版本。
class HarnessPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,64}$")]
    run_kind: HarnessRunKind
    allowed_symbols: tuple[ResearchSymbol, ...]
    symbol_admission: Literal["static", "research_directory"] = "static"
    allowed_capabilities: tuple[HarnessCapability, ...]

    @field_validator("allowed_symbols", "allowed_capabilities")
    @classmethod
    def validate_nonempty_and_deduplicated(
        cls,
        value: tuple[ResearchSymbol, ...] | tuple[HarnessCapability, ...],
    ) -> tuple[ResearchSymbol, ...] | tuple[HarnessCapability, ...]:
        if not value:
            raise ValueError("策略允许列表不能为空")
        if len(value) != len(set(value)):
            raise ValueError("策略允许列表不能包含重复项")
        return value


# 工作流执行前的安全拒绝，由运行时记录白名单评估及拒绝事件。
class HarnessPolicyViolation(RuntimeError):
    """Safe rejection raised before workflow invocation."""


# 固定工作流必须声明类别和所需能力；运行时在调用前核对授权。
class HarnessWorkflow[ResultT](Protocol):
    kind: HarnessRunKind
    required_capabilities: tuple[HarnessCapability, ...]

    async def run(self, request: HarnessRunRequest) -> ResultT: ...
