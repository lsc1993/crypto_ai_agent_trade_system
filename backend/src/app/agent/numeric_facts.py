# 综合研究数值边界：从结构化冻结事实建立目录，模型选择标识。
# 程序渲染带标签、单位和UTC时段的完整语句。
# 自由正文不接受报价或数量；本模块不从新闻/证据自由文本提取数字，也不证明自然语言因果解释正确。
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.market.contracts import Candle, UtcDateTime
from app.market.research_context import PublicResearchContext
from app.reports.factors import FactorAnalysis

_TOKEN = re.compile(r"\[\[fact:([a-f0-9]{24})\]\]")
_CHINESE_QUANTITY = re.compile(
    r"[零〇一二三四五六七八九十百千万亿两]{2,}|百分之|千分之|万分之|"
    r"[零〇一二三四五六七八九十百千万亿两]+点[零〇一二三四五六七八九]+|"
    r"[零〇一二三四五六七八九十百千万亿两]+(?:美元|美金|元|枚|张|倍|成|万|亿)"
)
_UNITS = {
    "USDT": "USDT",
    "USD": "USD",
    "base": "基础资产单位",
    "ratio": "比率",
    "percent": "%",
    "count": "项",
    "index": "指数点",
    "rate": "原始小数费率",
}


class NumericFact(BaseModel):
    """仅由服务端构造的事实；标识绑定值、字段标签、单位、证据与UTC范围，不由模型定义。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    evidence_id: UUID
    label: str = Field(min_length=1, max_length=160)
    value: Decimal
    unit: Literal["USDT", "USD", "base", "ratio", "percent", "count", "rate", "index"]
    observed_at: UtcDateTime
    time_semantics: Literal["observation", "conservative_reference"] = "observation"
    as_of: UtcDateTime | None = None
    window_start: UtcDateTime | None = None
    window_end: UtcDateTime | None = None

    @field_validator("value", mode="before")
    @classmethod
    def reject_float(cls, value: object) -> object:
        """金额不得经浮点中转；源JSON的金额应为字符串。"""
        if isinstance(value, (float, bool)):
            raise ValueError("事实数值不能使用浮点或布尔值")
        return value

    @field_validator("value")
    @classmethod
    def bounded_decimal(cls, value: Decimal) -> Decimal:
        """限制展开长度，避免NaN和巨大指数进入展示或指纹。"""
        if not value.is_finite() or abs(value.adjusted()) > 30:
            raise ValueError("事实数值必须有限且有界")
        if len(value.as_tuple().digits) > 60:
            raise ValueError("事实数值精度超限")
        return value

    @field_validator("observed_at", "as_of", "window_start", "window_end")
    @classmethod
    def utc_only(cls, value: datetime | None) -> datetime | None:
        """观察时刻与统计范围使用同一UTC口径，不能把无时区本地时间当UTC。"""
        if value is not None and (value.tzinfo is None or value.utcoffset() != timedelta(0)):
            raise ValueError("事实时间必须为带时区UTC")
        return value

    @model_validator(mode="after")
    def valid_window(self) -> NumericFact:
        """窗口必须成对提供且有序；事后抓取历史窗口允许晚于窗口的观察时间。"""
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("事实统计窗口必须完整")
        if self.window_start is not None and self.window_end is not None:
            if self.window_start >= self.window_end or self.window_end > (
                self.as_of or self.observed_at
            ):
                raise ValueError("事实统计窗口无效或包含未来数据")
        return self

    @property
    def token(self) -> str:
        """值或时段变化会生成不同标识，旧引用不能静默绑定新事实。"""
        payload = self.model_dump(mode="json")
        if self.as_of is None:
            # 新增统计截点不改变已有无截点事实的标识；有截点时必须纳入绑定。
            payload.pop("as_of")
        if self.time_semantics == "observation":
            payload.pop("time_semantics")
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        return "[[fact:" + hashlib.sha256(raw).hexdigest()[:24] + "]]"

    @property
    def statement(self) -> str:
        """渲染完整原子语句，禁止把裸数值交回模型自行添加开盘/收盘等标签。"""

        def stamp(value: datetime) -> str:
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

        scope = "观察时刻=" + stamp(self.observed_at)
        if self.time_semantics == "conservative_reference":
            scope = "单项观测时刻未单独提供；合并上下文参考时刻=" + stamp(self.observed_at)
        if self.as_of is not None:
            scope += ";统计截止=" + stamp(self.as_of)
        if self.window_start is not None and self.window_end is not None:
            scope += ";统计窗口=" + stamp(self.window_start) + "至" + stamp(self.window_end)
        return f"【{scope}；{self.label}={format(self.value, 'f')} {_UNITS[self.unit]}】"

    @property
    def reference_id(self) -> str:
        """独立引用数组使用不带正文标记的标识；保留旧token用于冻结样本回归。"""
        return self.token[7:-2]


class NumericReferenceError(ValueError):
    """只携带安全类别和契约字段位置，不携带模型原文或事实数值。"""

    def __init__(
        self,
        path: str,
        category: str = "numeric_reference",
        *,
        issues: Sequence[NumericReferenceError] | None = None,
        literal_kind: str | None = None,
        schema_kinds: tuple[str, ...] = (),
        hint: str | None = None,
    ) -> None:
        # 未知JSON键可能包含模型任意内容；只允许契约字段进入诊断和纠错提示。
        fields = {
            "horizon",
            "outlook",
            "confidence",
            "evidence_ids",
            "category",
            "direction",
            "topic",
            "fact_refs",
            "fact_id",
            "target",
            "market_overview",
            "headline",
            "summary",
            "short_term",
            "long_term",
            "heading",
            "thesis",
            "drivers",
            "label",
            "detail",
            "invalidation",
            "condition",
            "impact",
            "catalysts",
            "claim",
            "timing",
            "limitations",
            "risks_and_invalidation",
            "factor_interpretations",
        }
        parts = path.split(".")
        self.path = (
            path
            if len(path) <= 160
            and parts[0] in fields
            and all(
                part in fields or (part.isascii() and part.isdigit() and len(part) <= 3)
                for part in parts
            )
            else "schema"
        )
        self.category = category
        # 纠错提示只接受服务端构造的有界文本；不在这里拼接模型原文或事实数值。
        self.hint = _bounded_hint(hint)
        self.literal_kinds = (literal_kind,) if literal_kind else ()
        self.schema_kinds = schema_kinds
        collected = tuple(issues[:99]) if issues else (self,)
        self.issue_count = len(collected)
        self.field_paths = tuple(dict.fromkeys(issue.path for issue in collected))[:8]
        self.categories = tuple(sorted({issue.category for issue in collected}))
        self.literal_kinds = tuple(
            sorted({kind for issue in collected for kind in issue.literal_kinds})
        )
        self.schema_kinds = tuple(
            sorted({kind for issue in collected for kind in issue.schema_kinds})
        )
        self.hints = tuple(
            dict.fromkeys(issue.hint for issue in collected if issue.hint is not None)
        )[:8]
        super().__init__(category)


def _bounded_hint(value: str | None) -> str | None:
    """纠错提示只保留有界单行文本；调用方只能传入服务端构造的安全说明。"""
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized[:300] or None


def select_numeric_facts(facts: Sequence[NumericFact]) -> tuple[NumericFact, ...]:
    """可见目录最多十六条：按来源和字段轮询，同组优先首尾时点；不修改完整冻结事实。"""
    limit = 16
    if len(facts) <= limit:
        return tuple(facts)
    sources: dict[UUID, dict[str, list[NumericFact]]] = {}
    for fact in facts:
        sources.setdefault(fact.evidence_id, {}).setdefault(fact.label, []).append(fact)
    by_source = [list(fields.values()) for fields in sources.values()]
    groups: list[list[NumericFact]] = []
    # 先交错来源，再交错字段，避免一个来源的重复指标占满全部目录。
    for field_index in range(max(len(fields) for fields in by_source)):
        for fields in by_source:
            if field_index >= len(fields):
                continue
            ordered = sorted(
                fields[field_index],
                key=lambda f: (
                    f.window_start or f.observed_at,
                    f.window_end or f.observed_at,
                    f.token,
                ),
            )
            endpoints: list[NumericFact] = []
            left, right = 0, len(ordered) - 1
            while left <= right:
                endpoints.append(ordered[left])
                if left != right:
                    endpoints.append(ordered[right])
                left += 1
                right -= 1
            groups.append(endpoints)
    selected: list[NumericFact] = []
    for position in range(max(len(group) for group in groups)):
        for group in groups:
            if position < len(group):
                selected.append(group[position])
                if len(selected) == limit:
                    return tuple(selected)
    return tuple(selected)


def _is_numeric_claim_symbol(character: str) -> bool:
    """圈号等纯枚举标记不是数量；其余非十进制数字符号仍按数值符号拒绝。"""
    if not character.isnumeric():
        return False
    if character in "零〇一二三四五六七八九十百千万亿两":
        return False
    if "CIRCLED" in unicodedata.name(character, ""):
        return False
    return True


def contains_unbound_numeric_claim(value: str, *, symbol: str) -> bool:
    """只回答是否含自由数值，不返回原文；供句子级部分恢复判断。"""
    residual = _TOKEN.sub("", value).replace(symbol, "")
    if "[[" in residual or "]]" in residual:
        return True
    return (
        any(_is_numeric_claim_symbol(character) for character in residual)
        or _CHINESE_QUANTITY.search(residual) is not None
    )


def render_numeric_references(content: str, facts: Sequence[NumericFact], *, symbol: str) -> str:
    """在压缩与提案构造前拒绝自由数值，检查事实引用后渲染；未知/跨证据引用不修补。"""
    root = cast(JsonValue, json.loads(content))
    catalog = {fact.token: fact for fact in facts}
    issues: list[NumericReferenceError] = []

    def ids(value: JsonValue) -> set[str]:
        result: set[str] = set()
        if isinstance(value, dict):
            own = value.get("evidence_ids")
            if isinstance(own, list):
                return {item for item in own if isinstance(item, str)}
            for child in value.values():
                result.update(ids(child))
        if isinstance(value, list):
            for child in value:
                result.update(ids(child))
        return result

    def walk(value: JsonValue, path: str, inherited: set[str]) -> JsonValue:
        if isinstance(value, dict):
            scope = ids(value) or inherited
            return {
                key: child
                if key == "evidence_ids"
                else visit(child, f"{path}.{key}".strip("."), scope)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [visit(child, f"{path}.{index}", inherited) for index, child in enumerate(value)]
        if not isinstance(value, str):
            return value
        matches = list(_TOKEN.finditer(value))
        residual = _TOKEN.sub("", value).replace(symbol, "")
        if "[[" in residual or "]]" in residual:
            raise NumericReferenceError(path)
        if any(_is_numeric_claim_symbol(character) for character in residual) or (
            _CHINESE_QUANTITY.search(residual)
        ):
            if re.search(
                r"\d{4}[-/年]\d|\d{1,2}[:：]\d{2}|\d+\s*(?:小时|分钟|年|月|日|天)", residual
            ):
                kind = "date_time"
            elif re.search(r"\d+[.,]\d+", residual):
                kind = "decimal"
            elif any(c.isdecimal() for c in residual):
                kind = "integer"
            elif any(_is_numeric_claim_symbol(c) for c in residual):
                kind = "numeric_symbol"
            else:
                kind = "chinese_quantity"
            raise NumericReferenceError(path, "unbound_numeric_claim", literal_kind=kind)
        for match in matches:
            token = match.group()
            fact = catalog.get(token)
            if fact is None or str(fact.evidence_id) not in inherited:
                raise NumericReferenceError(path)
            # 占位符必须单独成行，不能在同一语句中被模型冠以另一个自由字段标签。
            if any(
                _TOKEN.search(line) and not _TOKEN.fullmatch(line.strip())
                for line in value.splitlines()
            ):
                raise NumericReferenceError(path)
        return _TOKEN.sub(lambda match: catalog[match.group()].statement, value)

    def visit(value: JsonValue, path: str, inherited: set[str]) -> JsonValue:
        """每个读者字段最多记一次错误，继续收集其他字段；有错时整份临时结果都会丢弃。"""
        try:
            return walk(value, path, inherited)
        except NumericReferenceError as error:
            if len(issues) < 99:
                issues.append(error)
            return None

    rendered = visit(root, "", ids(root))
    if issues:
        raise NumericReferenceError(issues[0].path, issues[0].category, issues=issues)
    return json.dumps(rendered, ensure_ascii=False)


def historical_candle_facts(
    candles: Sequence[Candle], *, evidence_id: UUID, observed_at: datetime
) -> tuple[NumericFact, ...]:
    """从单周期、严格有序且已收盘的结构化K线计算窗口事实与逐根OHLCV，不解析自由文本。"""
    if not candles:
        return ()
    first, last = candles[0], candles[-1]
    if any(
        c.symbol != first.symbol or c.timeframe != first.timeframe or c.close_at > observed_at
        for c in candles
    ) or any(a.close_at > b.open_at for a, b in zip(candles, candles[1:])):
        raise ValueError("历史事实K线范围无效")
    result: list[NumericFact] = []

    def add(
        label: str, value: Decimal, start: datetime, end: datetime, volume: bool = False
    ) -> None:
        result.append(
            NumericFact(
                evidence_id=evidence_id,
                label=label,
                value=value,
                unit="base" if volume else "USDT",
                observed_at=observed_at,
                window_start=start,
                window_end=end,
            )
        )

    for label, value in (
        ("历史窗口首根开盘价", first.open_price),
        ("历史窗口末根收盘价", last.close_price),
        ("历史窗口最低价", min(c.low_price for c in candles)),
        ("历史窗口最高价", max(c.high_price for c in candles)),
    ):
        add(label, value, first.open_at, last.close_at)
    for candle in candles:
        for label, value in (
            ("该根开盘价", candle.open_price),
            ("该根最高价", candle.high_price),
            ("该根最低价", candle.low_price),
            ("该根收盘价", candle.close_price),
            ("该根成交量", candle.volume),
        ):
            add(label, value, candle.open_at, candle.close_at, label == "该根成交量")
    return tuple(result)


def snapshot_numeric_facts(
    payload: Mapping[str, JsonValue], *, evidence_id: UUID, observed_at: datetime
) -> tuple[NumericFact, ...]:
    """只读取结构化快照的白名单字段，未知字段/新闻内容不生成数值事实。"""
    result: list[NumericFact] = []
    summary = payload.get("summary")
    if isinstance(summary, dict):
        fields = {
            "price": ("市场快照价格", "USDT"),
            "change24h": ("快照过去日涨跌幅", "percent"),
            "volume24h": ("快照过去日成交额", "USDT"),
            "fundingRate": ("快照资金费率", "rate"),
            "openInterest": ("快照持仓量", "base"),
        }
        for key, (label, unit) in fields.items():
            value = summary.get(key)
            if isinstance(value, str):
                result.append(
                    NumericFact.model_validate(
                        dict(
                            evidence_id=evidence_id,
                            label=label,
                            value=value,
                            unit=unit,
                            observed_at=observed_at,
                        )
                    )
                )
    context = payload.get("context")
    if isinstance(context, dict):
        # 使用真实契约解析，避免camelCase/snake_case猜测导致整组指标静默丢失。
        parsed = PublicResearchContext.model_validate(context)
        fields = (
            ("快照基差率", parsed.basis_rate, "ratio"),
            ("快照多空账户比", parsed.long_short_account_ratio, "ratio"),
            ("快照主动成交比", parsed.taker_buy_sell_ratio, "ratio"),
            ("快照恐惧贪婪指数", Decimal(parsed.fear_greed_value), "index"),
            ("快照恐惧贪婪周变化", Decimal(parsed.fear_greed_change_7d), "index"),
        )
        for label, value, unit in fields:
            result.append(
                NumericFact.model_validate(
                    dict(
                        evidence_id=evidence_id,
                        label=label,
                        value=value,
                        unit=unit,
                        observed_at=parsed.observed_at,
                        time_semantics="conservative_reference",
                    )
                )
            )
    return tuple(result)


def factor_numeric_facts(analysis: FactorAnalysis | None) -> tuple[NumericFact, ...]:
    """仅使用单一冻结来源专题中已声明的数值/单位；文本、缺失和多源歧义不猜测绑定。"""
    if analysis is None:
        return ()
    result: list[NumericFact] = []
    # ETF需另外绑定交易日期及累计日期范围；没有类型化日期目录时保留专题区数值，正文只做定性解释。
    for topic in (analysis.policy, analysis.funding):
        if (
            topic.status not in {"available", "partial"}
            or len(topic.evidence_ids) != 1
            or topic.observed_at is None
        ):
            continue
        for fact in topic.facts:
            if fact.unit == "text" or fact.value is None:
                continue
            try:
                value = Decimal(fact.value)
                # 最新结算是单点，其余统计保留真实观测时刻和独立研究截止，不能将截止当成新观测。
                point = fact.label == "最新已结算费率"
                result.append(
                    NumericFact(
                        evidence_id=topic.evidence_ids[0],
                        label=fact.label,
                        value=value,
                        unit="USD" if fact.unit == "usd" else fact.unit,
                        observed_at=topic.observed_at,
                        as_of=None if point else topic.window_end,
                        window_start=None if point else topic.window_start,
                        window_end=topic.window_end
                        if topic.window_start is not None and not point
                        else None,
                    )
                )
            except (InvalidOperation, ValueError):
                # 范围/复合描述不是单个十进制数，保持定性可用而不伪造一个标量。
                continue
    return tuple(result)
