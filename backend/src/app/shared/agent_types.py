# 定义实盘手动计划 Agent 的共享不可变类型：版本引用、产品键、十进制文本和分页。
# 这些类型只表达数据契约，不依赖 Agent、SQLAlchemy、交易执行或私有账户。
# 外部 API 字段使用驼峰别名；内部序列化保留字段名，金额与价格统一走十进制字符串。
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Annotated, Literal, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    PlainSerializer,
    field_validator,
)

from app.market.contracts import UtcDateTime
from app.market.symbols import ResearchSymbol

JsonObject = dict[str, JsonValue]
ItemT = TypeVar("ItemT")

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_DECIMAL_TEXT_PATTERN = re.compile(r"-?[0-9]{1,30}(?:\.[0-9]{1,18})?\Z")
_MAX_ABS_DECIMAL = Decimal("1" * 30)


# 公共契约异常携带稳定错误码，调用方据此映射安全错误而不回显上游细节。
class AgentContractError(ValueError):
    # 保存固定原因码；异常文本只用于本地诊断，不直接作为 API 响应。
    def __init__(self, message: str, *, code: str = "agent_contract_violation") -> None:
        super().__init__(message)
        self.code = code


# 将 snake_case 字段转成前端约定的 camelCase 别名。
def _camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(word.capitalize() for word in tail)


# 所有新领域模型共享冻结、拒绝额外字段和驼峰序列化配置。
class AgentModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        frozen=True,
        extra="forbid",
    )


# 校验 64 位小写十六进制内容指纹；大小写或长度不符都拒绝。
def is_sha256(value: str) -> bool:
    return _SHA256_PATTERN.fullmatch(value) is not None


# 公开 JSON 规范化哈希：键排序、紧凑分隔并使 NaN 失败，保证候选和请求指纹可复现。
def sha256_json(value: JsonValue) -> str:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise TypeError("只能对 JSON 安全值计算指纹") from error
    return sha256(serialized.encode("utf-8")).hexdigest()


# 解析 API 十进制文本：拒绝布尔、浮点、指数、NaN/Infinity 和超出位数范围的值。
# 内部 Decimal 输入仅在位数范围内允许，便于领域代码复用同一字段而不引入字符串往返。
def parse_decimal_text(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("金融数值不能是布尔值")
    if isinstance(value, str):
        if _DECIMAL_TEXT_PATTERN.fullmatch(value) is None:
            raise ValueError("金融数值必须是非指数十进制字符串")
        try:
            parsed = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("金融数值必须是有效十进制数") from error
    elif isinstance(value, Decimal):
        parsed = value
    else:
        raise ValueError("金融数值必须是字符串或 Decimal")
    if not parsed.is_finite():
        raise ValueError("金融数值必须有限")
    if abs(parsed) > _MAX_ABS_DECIMAL:
        raise ValueError("金融数值整数部分最多 30 位")
    exponent = parsed.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -18:
        raise ValueError("金融数值小数部分最多 18 位")
    return parsed


# 序列化为无指数、无多余尾零的十进制文本；内部计算精度不因展示被改写。
def serialize_decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("金融数值必须有限")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


# 接受字符串或内部 Decimal，JSON 输出固定为十进制字符串。
DecimalText = Annotated[
    Decimal,
    BeforeValidator(parse_decimal_text),
    PlainSerializer(serialize_decimal_text, return_type=str, when_used="json"),
]


# 校验带零时区的时间；不接受本地时区、无时区或非 UTC 偏移。
def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是带时区的 UTC")
    return value


# 指向不可变版本的标识与内容指纹；引用本身不内嵌完整正文。
class VersionRef(AgentModel):
    version_id: UUID
    sha256: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("版本指纹必须是 64 位小写十六进制")
        return value


# 指向已保存产物的引用；只允许通过引用传递大载荷，不把完整计划放进事件或模型上下文。
class ArtifactRef(AgentModel):
    artifact_id: UUID
    sha256: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("产物指纹必须是 64 位小写十六进制")
        return value


# 首期规划产品固定 Binance USDT 线性永续；改变枚举需要单独的产品与规则验收。
class ProductKey(AgentModel):
    venue: Literal["binance_usdm"]
    symbol: ResearchSymbol
    settlement: Literal["USDT"]
    kind: Literal["linear_perpetual"]


# 统一分页输入；只允许正整数页码和最多 100 条的页大小。
class PageQuery(AgentModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


# 统一分页输出；items 的具体元素类型由调用方精确绑定。
class VersionPage[ItemT](AgentModel):
    items: tuple[ItemT, ...]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


__all__ = [
    "AgentContractError",
    "AgentModel",
    "ArtifactRef",
    "DecimalText",
    "JsonObject",
    "PageQuery",
    "ProductKey",
    "UtcDateTime",
    "VersionPage",
    "VersionRef",
    "is_sha256",
    "parse_decimal_text",
    "require_utc",
    "serialize_decimal_text",
    "sha256_json",
]
