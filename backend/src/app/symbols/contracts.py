# 目录契约：研究标识、能力检查、目录版本与带租约同步任务组成对外状态；来源缺失、
# 失败和不支持分别表达。
# 研究币种目录：公开合约检查通过后登记币种并排队初始同步；研究准入不扩展交易契约。
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, field_validator
from pydantic.alias_generators import to_camel

from app.market.contracts import UtcDateTime
from app.market.symbols import ResearchSymbol


# 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是带时区的 UTC 时间")
    return value


SymbolUtcTime = Annotated[UtcDateTime, AfterValidator(_require_utc)]
CapabilityName = Literal["market", "candles", "derivatives", "funding", "news", "sentiment", "etf"]
SyncStatus = Literal["queued", "running", "ready", "partial", "failed", "cancelled"]
SourceStatus = Literal["available", "partial", "missing", "failed", "unsupported"]


# 目录契约公共基类，冻结值、禁止额外字段并以驼峰命名输出。
class SymbolModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
        frozen=True,
    )


# 新增研究标识和新闻关键词请求，规范化标识并约束关键词形态和数量。
class SymbolInput(SymbolModel):
    symbol: ResearchSymbol
    keywords: tuple[str, ...] = Field(default=(), max_length=20)

    # 校验symbol 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    # 校验keywords 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：新闻关键词须为 2–60 字符的名称，不支持网址或正则表达式。
    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: dict[str, str] = {}
        for value in values:
            keyword = " ".join(value.split())
            if not 2 <= len(keyword) <= 60 or not re.fullmatch(r"[\w -]+", keyword):
                raise ValueError("新闻关键词须为 2–60 字符的名称，不支持网址或正则表达式")
            normalized.setdefault(keyword.casefold(), keyword)
        return tuple(normalized.values())


# 单项公开来源能力与安全说明，未验证与明确不支持分别表达。
class Capability(SymbolModel):
    name: CapabilityName
    status: Literal["supported", "unsupported", "unverified"]
    message: str


# 研究准入用的公开合约属性，包括基础、报价、保证金资产与合约状态。
class MarketMetadata(SymbolModel):
    symbol: ResearchSymbol
    base_asset: str
    quote_asset: str
    margin_asset: str
    contract_type: str
    status: str


# 公开能力检查结果，汇集整体准入判定、分项能力和可用元数据。
class CheckResult(SymbolModel):
    symbol: ResearchSymbol
    supported: bool
    checks: tuple[Capability, ...]
    metadata: MarketMetadata | None = None


# 逐来源同步结果，保存覆盖状态、载荷哈希和安全提示。
class SyncSource(SymbolModel):
    name: CapabilityName
    status: SourceStatus
    message: str
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


# 带版本和租约身份的同步任务，关联生命周期、来源结果与市场快照。
class SyncRun(SymbolModel):
    id: UUID
    symbol: ResearchSymbol
    version: int = Field(ge=1)
    status: SyncStatus
    stage: str
    created_at: SymbolUtcTime
    started_at: SymbolUtcTime | None = None
    completed_at: SymbolUtcTime | None = None
    lease_token: UUID | None = None
    lease_until: SymbolUtcTime | None = None
    snapshot_id: UUID | None = None
    sources: tuple[SyncSource, ...] = ()
    error: str | None = None


# 研究目录记录，保存准入、归档、关键词、能力与最近同步，不授予交易权限。
class ResearchSymbolEntry(SymbolModel):
    symbol: ResearchSymbol
    base_asset: str
    quote_asset: str
    margin_asset: str
    contract_type: str
    enabled: bool
    keywords: tuple[str, ...] = ()
    capabilities: tuple[Capability, ...] = ()
    version: int = Field(ge=1)
    created_at: SymbolUtcTime
    archived_at: SymbolUtcTime | None = None
    can_research: bool = False
    last_sync: SyncRun | None = None


# 研究目录列表响应，封装研究条目元组。
class SymbolList(SymbolModel):
    items: tuple[ResearchSymbolEntry, ...]


# 目录安全领域错误，携带稳定错误码、HTTP 状态与受限详情。
class SymbolError(RuntimeError):
    # 初始化本实例依赖和配置；输入 code、message、status_code、details。
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 409,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = {} if details is None else details
