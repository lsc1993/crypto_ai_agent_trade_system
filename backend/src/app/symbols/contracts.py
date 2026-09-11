from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, field_validator
from pydantic.alias_generators import to_camel

from app.market.contracts import UtcDateTime
from app.market.symbols import ResearchSymbol


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是带时区的 UTC 时间")
    return value


SymbolUtcTime = Annotated[UtcDateTime, AfterValidator(_require_utc)]
CapabilityName = Literal["market", "candles", "derivatives", "funding", "news", "sentiment", "etf"]
SyncStatus = Literal["queued", "running", "ready", "partial", "failed", "cancelled"]
SourceStatus = Literal["available", "partial", "missing", "failed", "unsupported"]


class SymbolModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
        frozen=True,
    )


class SymbolInput(SymbolModel):
    symbol: ResearchSymbol
    keywords: tuple[str, ...] = Field(default=(), max_length=20)

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

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


class Capability(SymbolModel):
    name: CapabilityName
    status: Literal["supported", "unsupported", "unverified"]
    message: str


class MarketMetadata(SymbolModel):
    symbol: ResearchSymbol
    base_asset: str
    quote_asset: str
    margin_asset: str
    contract_type: str
    status: str


class CheckResult(SymbolModel):
    symbol: ResearchSymbol
    supported: bool
    checks: tuple[Capability, ...]
    metadata: MarketMetadata | None = None


class SyncSource(SymbolModel):
    name: CapabilityName
    status: SourceStatus
    message: str
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


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


class SymbolList(SymbolModel):
    items: tuple[ResearchSymbolEntry, ...]


class SymbolError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
