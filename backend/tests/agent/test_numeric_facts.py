# 用固定结构化事实验证数值引用、单位/UTC时段绑定与自由数值拒绝；不调用模型或网络。
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from uuid import UUID

import pytest

EVIDENCE = UUID("10000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)


def fact():
    """标签和数值由程序构造，模型只能引用整条事实，不能另配自由标签。"""
    module = import_module("app.agent.numeric_facts")
    return module.NumericFact(
        evidence_id=EVIDENCE,
        label="历史窗口最低价",
        value=Decimal("76444.00"),
        unit="USDT",
        observed_at=NOW,
        window_start=NOW.replace(hour=0),
        window_end=NOW,
    )


def test_reference_renders_complete_bound_statement():
    """渲染同时保留字段、单位与统计时段；不是向模型自由标签中只替换一个裸数字。"""
    module = import_module("app.agent.numeric_facts")
    value = fact()
    raw = json.dumps({"market_overview": {"summary": value.token, "evidence_ids": [str(EVIDENCE)]}})
    rendered = json.loads(module.render_numeric_references(raw, (value,), symbol="BTCUSDT"))
    text = rendered["market_overview"]["summary"]
    assert "历史窗口最低价" in text and "76444.00 USDT" in text
    assert "2026-10-30T00:00:00Z" in text and "2026-10-30T12:00:00Z" in text
    assert "[[fact:" not in text


@pytest.mark.parametrize(
    "text",
    [
        "开盘77208.20",
        "低点７６７１７",
        "价格七万七千美元",
        "上涨百分之三",
        "从07:00反弹",
        "价格七七二〇八",
    ],
)
def test_free_numbers_rejected_even_if_present_in_evidence(text: str):
    """存在于输入的数值也可能字段或时段错误，故未经绑定不能在模型正文自由输出。"""
    module = import_module("app.agent.numeric_facts")
    with pytest.raises(module.NumericReferenceError):
        module.render_numeric_references(json.dumps({"summary": text}), (fact(),), symbol="BTCUSDT")


def test_unknown_and_wrong_evidence_references_rejected():
    """未知token和引用合法事实但借用另一证据ID都必须拒绝。"""
    module = import_module("app.agent.numeric_facts")
    for text, ids in [("[[fact:unknown]]", [str(EVIDENCE)]), (fact().token, [str(UUID(int=2))])]:
        with pytest.raises(module.NumericReferenceError):
            module.render_numeric_references(
                json.dumps({"summary": text, "evidence_ids": ids}), (fact(),), symbol="BTCUSDT"
            )


def test_qualitative_text_and_symbol_digits_remain_valid():
    """正常中文数量词不是价格断言；研究币种名称本身的数字不应误判为模型报价。"""
    module = import_module("app.agent.numeric_facts")
    raw = json.dumps({"summary": "1000SHIBUSDT 数天至两周的证据不足，另一种解释需要复核。"})
    assert json.loads(module.render_numeric_references(raw, (), symbol="1000SHIBUSDT"))[
        "summary"
    ].startswith("1000SHIB")


def test_nonfinite_values_and_naive_times_rejected():
    """事实目录自身也必须拒绝非有限金额、浮点输入和无时区时间，防止渲染不可信值。"""
    module = import_module("app.agent.numeric_facts")
    for kwargs in (
        {"value": "NaN"},
        {"value": 1.1},
        {"value": "0E-1000000"},
        {"observed_at": NOW.replace(tzinfo=None)},
    ):
        payload = fact().model_dump()
        payload.update(kwargs)
        with pytest.raises(ValueError):
            module.NumericFact.model_validate(payload)


def test_inline_reference_cannot_borrow_another_standalone_occurrence():
    """同一token另有合法独占行也不能掩盖带错误自由标签的内联引用。"""
    module = import_module("app.agent.numeric_facts")
    raw = json.dumps(
        {"summary": fact().token + "\n开盘价为" + fact().token, "evidence_ids": [str(EVIDENCE)]}
    )
    with pytest.raises(module.NumericReferenceError):
        module.render_numeric_references(raw, (fact(),), symbol="BTCUSDT")


def test_historical_facts_keep_window_low_distinct_from_first_candle_low():
    """回归真实错配：窗口最低、首根低点、开盘与收盘必须有不同标签和内容指纹。"""
    from app.market.contracts import Candle

    module = import_module("app.agent.numeric_facts")
    raw = json.loads(
        (Path(__file__).parents[2] / "evaluation/real-model/historical-market.json").read_bytes()
    )
    candles = tuple(Candle.model_validate(c) for c in raw["candles"])
    values = module.historical_candle_facts(candles, evidence_id=EVIDENCE, observed_at=NOW)
    by_label = {f.label: f for f in values[:4]}
    assert by_label["历史窗口最低价"].value == Decimal("76444.00")
    assert by_label["历史窗口首根开盘价"].value == Decimal("77962.60")
    first_low = next(f for f in values if f.label == "该根最低价")
    assert first_low.value == Decimal("76717.00")
    assert first_low.token != by_label["历史窗口最低价"].token
    assert first_low.window_start == candles[0].open_at
    with pytest.raises(ValueError):
        module.historical_candle_facts(candles[::-1], evidence_id=EVIDENCE, observed_at=NOW)
    with pytest.raises(ValueError):
        module.historical_candle_facts(
            candles, evidence_id=EVIDENCE, observed_at=NOW.replace(hour=11)
        )


def test_snapshot_fact_units_do_not_confuse_quote_volume_with_asset_volume():
    """生产快照的成交额是quoteVolume，不能渲染成K线的基础资产成交量。"""
    module = import_module("app.agent.numeric_facts")
    values = module.snapshot_numeric_facts(
        {"summary": {"price": "77962.60", "volume24h": "123456.00"}},
        evidence_id=EVIDENCE,
        observed_at=NOW,
    )
    assert len(values) == 2
    assert values[1].unit == "USDT"
    assert "成交额" in values[1].statement


def test_factor_observation_does_not_become_report_cutoff():
    """最近结算观测时间与统计截止不同，不能为了满足窗口校验伪造较新的观测时间。"""
    from app.reports.factors import FactorAnalysis, FactorFact, FactorTopic

    module = import_module("app.agent.numeric_facts")
    observed = NOW - timedelta(hours=1)
    topic = FactorTopic(
        status="partial",
        window_start=NOW - timedelta(days=7),
        window_end=NOW,
        observed_at=observed,
        evidence_ids=(EVIDENCE,),
        facts=(
            FactorFact(label="最新已结算费率", value="0.0001", unit="rate"),
            FactorFact(label="已获取样本平均费率", value="0.0002", unit="rate"),
        ),
    )
    missing = FactorTopic(status="missing", window_end=NOW)
    facts = module.factor_numeric_facts(FactorAnalysis(policy=missing, funding=topic, etf=missing))
    assert facts[0].observed_at == observed
    assert facts[0].window_start is None
    assert facts[1].observed_at == observed and facts[1].as_of == NOW
    assert facts[1].window_end == NOW


def test_etf_without_typed_trading_dates_does_not_invent_current_flow_date():
    """只有报告截止而没有可绑定交易日期的专题，不应把净流量冒充该日的金额。"""
    from app.reports.factors import FactorAnalysis, FactorFact, FactorTopic

    module = import_module("app.agent.numeric_facts")
    etf = FactorTopic(
        status="partial",
        window_end=NOW,
        fetched_at=NOW,
        evidence_ids=(EVIDENCE,),
        facts=(FactorFact(label="最新交易日净流量", value="123.00", unit="usd"),),
    )
    missing = FactorTopic(status="missing", window_end=NOW)
    assert (
        module.factor_numeric_facts(FactorAnalysis(policy=missing, funding=missing, etf=etf)) == ()
    )


def test_real_context_projection_uses_actual_field_names_and_reference_time():
    """真实上下文使用snake_case，合并min时刻不是每个指标各自的实际观测时间。"""
    from app.market.contracts import FreshnessStatus
    from app.market.research_context import PublicResearchContext

    module = import_module("app.agent.numeric_facts")
    context = PublicResearchContext(
        symbol="BTCUSDT",
        basis_rate=Decimal("0.01"),
        long_short_account_ratio=Decimal("1.2"),
        taker_buy_sell_ratio=Decimal("1.3"),
        fear_greed_value=50,
        fear_greed_classification="Neutral",
        fear_greed_change_7d=2,
        fear_greed_7d_start_at=NOW - timedelta(days=7),
        freshness=FreshnessStatus.FRESH,
        observed_at=NOW.replace(hour=0),
        fetched_at=NOW,
    )
    values = module.snapshot_numeric_facts(
        {"context": context.model_dump(mode="json")},
        evidence_id=EVIDENCE,
        observed_at=context.observed_at,
    )
    assert len(values) == 5
    assert values[0].value == Decimal("0.01") and values[3].value == Decimal("50")
    assert all(f.time_semantics == "conservative_reference" for f in values)
    assert all("单项观测时刻未单独提供" in f.statement for f in values)
    assert all("合并上下文参考时刻=" in f.statement for f in values)
    assert all("【观察时刻=" not in f.statement for f in values)


def test_visible_catalog_is_bounded_diverse_and_keeps_temporal_endpoints():
    """重复K线字段不应淹没目录，筛选保留不同来源/字段并优先选同组首尾观测。"""
    module = import_module("app.agent.numeric_facts")
    values = tuple(
        module.NumericFact(
            evidence_id=EVIDENCE,
            label="该根成交量",
            value=Decimal(i),
            unit="base",
            observed_at=NOW - timedelta(minutes=40 - i),
        )
        for i in range(40)
    )
    other = module.NumericFact(
        evidence_id=UUID(int=2),
        label="快照价格",
        value=Decimal("123.45"),
        unit="USDT",
        observed_at=NOW,
    )
    selected = module.select_numeric_facts((*values, other))
    assert len(selected) == 16
    assert values[0] in selected and values[-1] in selected and other in selected
    assert selected == module.select_numeric_facts((*values, other))
    assert all(fact in (*values, other) for fact in selected)


def test_numeric_diagnostics_are_aggregated_but_bounded():
    """拒绝整份候选，同时将诊断位置限制为八项，不能保存各字段原文。"""
    module = import_module("app.agent.numeric_facts")
    with pytest.raises(module.NumericReferenceError) as error:
        module.render_numeric_references(
            json.dumps({"limitations": ["private-marker 123"] * 12}), (), symbol="BTCUSDT"
        )
    assert error.value.issue_count == 12
    assert len(error.value.field_paths) == 8
    assert "private-marker" not in str(error.value)
