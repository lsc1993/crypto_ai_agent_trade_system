# 独立事实数组协议的离线回归：正文与事实选择分开，程序只追加已绑定的完整语句。
# 全部数据为合成夹具，无网络、真实密钥、订单或数据库访问。
import json
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module
from typing import Any, cast
from uuid import UUID

import pytest

EVIDENCE = UUID(int=1)


def setup_case() -> tuple[Any, Any, dict[str, Any]]:
    """固定证据与价格事实，原文故意不含任何价格，引用只存在于独立数组。"""
    module = import_module("app.agent.fact_references")
    fact = module.NumericFact(
        evidence_id=EVIDENCE,
        label="窗口最低价",
        value=Decimal("123.40"),
        unit="USDT",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    body = {
        "market_overview": {"summary": "冻结证据仍需复核。", "evidence_ids": [str(EVIDENCE)]},
        "fact_refs": [{"target": "market_overview.summary", "fact_id": fact.reference_id}],
    }
    return module, fact, body


def test_structured_refs_render_complete_statement_and_remove_transport_field() -> None:
    """最终字符串兼容旧报告，新增传输字段不进入持久化或HTTP契约。"""
    module, fact, body = setup_case()
    out = json.loads(
        module.render_structured_fact_references(json.dumps(body), (fact,), symbol="BTCUSDT")
    )
    assert out["market_overview"]["summary"] == "冻结证据仍需复核。\n" + fact.statement
    assert "fact_refs" not in out and "[[fact:" not in json.dumps(out)


def test_partial_render_drops_mismatched_ref_and_keeps_qualitative_text() -> None:
    """可定位的绑定失败只丢弃该事实，定性正文和其他合法事实仍保留。"""
    module, fact, body = setup_case()
    body["market_overview"]["evidence_ids"] = [str(UUID(int=2))]
    result = module.render_structured_fact_references_partially(
        json.dumps(body), (fact,), symbol="BTCUSDT"
    )
    out = json.loads(result.content)
    assert result.dropped_count == 1
    assert "fact_evidence_mismatch" in result.dropped_categories
    assert out["market_overview"]["summary"] == "冻结证据仍需复核。"
    assert "fact_refs" not in out


def test_partial_render_keeps_valid_refs_and_drops_duplicate() -> None:
    """部分恢复只移除失败项，合法事实不得因同批重复项一起丢失。"""
    module, fact, body = setup_case()
    binding = body["fact_refs"][0]
    body["fact_refs"] = [dict(binding), dict(binding)]
    result = module.render_structured_fact_references_partially(
        json.dumps(body), (fact,), symbol="BTCUSDT"
    )
    out = json.loads(result.content)
    assert result.dropped_count == 1
    assert "duplicate_fact_reference" in result.dropped_categories
    assert out["market_overview"]["summary"].count(fact.statement) == 1


def test_partial_render_redacts_unbound_numeric_sentence() -> None:
    """部分恢复会按句删掉自由数字，保留其余正文和合法事实。"""
    module, fact, body = setup_case()
    body["market_overview"]["evidence_ids"] = [str(UUID(int=2))]
    body["market_overview"]["summary"] = "冻结证据仍需复核。错误价格123.40。"
    result = module.render_structured_fact_references_partially(
        json.dumps(body), (fact,), symbol="BTCUSDT"
    )
    out = json.loads(result.content)
    assert result.dropped_count == 1
    assert result.redacted_claim_count == 1
    assert "123.40" not in out["market_overview"]["summary"]
    assert "含未绑定数值的句子已省略" in out["market_overview"]["summary"]


def test_partial_render_rejects_number_in_non_redactable_field() -> None:
    """标题等非叙述字段不能被替换成空壳，必须回到整份拒绝。"""
    module, fact, body = setup_case()
    body["market_overview"]["headline"] = "价格123.40"
    with pytest.raises(module.NumericReferenceError):
        module.render_structured_fact_references_partially(
            json.dumps(body), (fact,), symbol="BTCUSDT"
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_fact",
        "unknown_target",
        "thesis_target",
        "wrong_evidence",
        "duplicate",
        "inline",
        "free_number",
        "extra_key",
    ],
)
def test_invalid_structured_refs_reject_whole_proposal(mutation: str) -> None:
    """无法绑定或正文仍含原始数值时拒绝整份，不返回部分渲染结果。"""
    module, fact, body = setup_case()
    binding = body["fact_refs"][0]
    if mutation == "unknown_fact":
        binding["fact_id"] = "f" * 24
    elif mutation == "unknown_target":
        binding["target"] = "private_unknown_key"
    elif mutation == "thesis_target":
        binding["target"] = "long_term.thesis"
    elif mutation == "wrong_evidence":
        body["market_overview"]["evidence_ids"] = [str(UUID(int=2))]
    elif mutation == "duplicate":
        body["fact_refs"].append(dict(binding))
    elif mutation == "inline":
        body["market_overview"]["summary"] = fact.token
    elif mutation == "free_number":
        body["market_overview"]["summary"] = "错误价格123.40。"
    elif mutation == "extra_key":
        binding["private_unknown_key"] = "private-marker"
    with pytest.raises(module.NumericReferenceError) as error:
        module.render_structured_fact_references(json.dumps(body), (fact,), symbol="BTCUSDT")
    assert "private-marker" not in str(error.value)
    if mutation in {"unknown_target", "thesis_target", "wrong_evidence", "duplicate", "extra_key"}:
        # 纠错提示只含契约路径、事实标签和 evidence UUID，不能回显未知键。
        assert error.value.hints
        assert "private-marker" not in " ".join(error.value.hints)


def test_qualitative_legacy_shape_can_omit_empty_refs() -> None:
    """纯定性旧形状可兼容，兼容不包含旧内联数字引用或回写历史。"""
    module, _, body = setup_case()
    body.pop("fact_refs")
    assert (
        json.loads(module.render_structured_fact_references(json.dumps(body), (), symbol="BTCUSDT"))
        == body
    )


@pytest.mark.parametrize("target", ["short_term.thesis", "long_term.thesis"])
def test_thesis_targets_are_not_reference_targets(target: str) -> None:
    """thesis 没有自身 evidence_ids；即使 drivers 引用证据，也不能把事实挂到 thesis。"""
    module, fact, body = setup_case()
    cited = {"evidence_ids": [str(EVIDENCE)]}
    body["short_term"] = {"thesis": "待复核。", "drivers": [{**cited, "detail": "待复核。"}]}
    body["long_term"] = {"thesis": "待复核。", "drivers": [{**cited, "detail": "待复核。"}]}
    body["fact_refs"] = [{"target": target, "fact_id": fact.reference_id}]
    with pytest.raises(module.NumericReferenceError) as error:
        module.render_structured_fact_references(json.dumps(body), (fact,), symbol="BTCUSDT")
    assert "unknown_fact_target" in error.value.categories
    assert error.value.hints


def test_market_overview_can_bind_facts_from_multiple_evidence_groups() -> None:
    """一个段落可列多个 evidence_id；不同来源的事实不需要拆成同一目标。"""
    module, fact, body = setup_case()
    second_evidence = UUID(int=2)
    second = fact.model_copy(
        update={
            "evidence_id": second_evidence,
            "label": "第二字段",
            "value": Decimal("456.70"),
        }
    )
    body["market_overview"]["evidence_ids"] = [str(EVIDENCE), str(second_evidence)]
    body["fact_refs"] = [
        {"target": "market_overview.summary", "fact_id": fact.reference_id},
        {"target": "market_overview.summary", "fact_id": second.reference_id},
    ]
    out = json.loads(
        module.render_structured_fact_references(json.dumps(body), (fact, second), symbol="BTCUSDT")
    )
    summary = out["market_overview"]["summary"]
    assert fact.statement in summary and second.statement in summary


def test_uppercase_or_compact_evidence_uuid_is_canonicalized() -> None:
    """UUID 大小写或连字符差异不能把合法证据误判成另一来源。"""
    module, fact, body = setup_case()
    body["market_overview"]["evidence_ids"] = [str(EVIDENCE).upper().replace("-", "")]
    out = json.loads(
        module.render_structured_fact_references(json.dumps(body), (fact,), symbol="BTCUSDT")
    )
    assert fact.statement in out["market_overview"]["summary"]


def test_target_indices_must_be_canonical() -> None:
    """零填充下标不能形成同一段落的不同字符串别名以绕过重复/数量校验。"""
    module, fact, body = setup_case()
    body["short_term"] = {
        "drivers": [{"detail": "短期证据待复核。", "evidence_ids": [str(EVIDENCE)]}]
    }
    body["fact_refs"] = [{"target": "short_term.drivers.00.detail", "fact_id": fact.reference_id}]
    with pytest.raises(module.NumericReferenceError):
        module.render_structured_fact_references(json.dumps(body), (fact,), symbol="BTCUSDT")


@pytest.mark.parametrize("value", [None, {}, [None] * 17])
def test_reference_array_shape_and_global_budget_are_bounded(value: object) -> None:
    """只接受有界数组，空对象/null或超过十六项都不能被当成没有引用。"""
    module, fact, body = setup_case()
    body["fact_refs"] = value
    with pytest.raises(module.NumericReferenceError):
        module.render_structured_fact_references(json.dumps(body), (fact,), symbol="BTCUSDT")


def test_per_target_reference_budget_rejects_whole_candidate() -> None:
    """多个合法事实也不能超出每段五条上限，失败不返回先插入的五条。"""
    module, fact, body = setup_case()
    facts = tuple(
        fact.model_copy(update={"label": label})
        for label in ("甲字段", "乙字段", "丙字段", "丁字段", "戊字段", "己字段")
    )
    body["fact_refs"] = [
        {"target": "market_overview.summary", "fact_id": f.reference_id} for f in facts
    ]
    with pytest.raises(module.NumericReferenceError) as error:
        module.render_structured_fact_references(json.dumps(body), facts, symbol="BTCUSDT")
    assert "excess_fact_reference" in error.value.categories
    assert error.value.hints


def test_per_target_reference_budget_accepts_five_distinct_facts() -> None:
    """每段五条是当前上限，五条不同事实应全部渲染而不是提前拒绝。"""
    module, fact, body = setup_case()
    facts = tuple(
        fact.model_copy(update={"label": label})
        for label in ("甲字段", "乙字段", "丙字段", "丁字段", "戊字段")
    )
    body["fact_refs"] = [
        {"target": "market_overview.summary", "fact_id": f.reference_id} for f in facts
    ]
    out = json.loads(
        module.render_structured_fact_references(json.dumps(body), facts, symbol="BTCUSDT")
    )
    summary = out["market_overview"]["summary"]
    assert all(f.statement in summary for f in facts)


def test_duplicate_and_excess_categories_are_distinct() -> None:
    """重复引用与单段超额要给出不同类别，纠错才能指向删除还是移动。"""
    module, fact, body = setup_case()
    binding = body["fact_refs"][0]
    body["fact_refs"] = [dict(binding), dict(binding)]
    with pytest.raises(module.NumericReferenceError) as duplicate:
        module.render_structured_fact_references(json.dumps(body), (fact,), symbol="BTCUSDT")
    assert "duplicate_fact_reference" in duplicate.value.categories
    assert "excess_fact_reference" not in duplicate.value.categories


@pytest.mark.parametrize(
    "target",
    [
        "short_term.drivers.0.detail",
        "short_term.invalidation.0.condition",
        "long_term.drivers.0.detail",
        "long_term.invalidation.0.impact",
        "catalysts.0.claim",
        "risks_and_invalidation.0.impact",
        "factor_interpretations.0.summary",
    ],
)
def test_valid_target_positions_use_local_evidence(target: str) -> None:
    """各类目标使用已有正文与各自引用集合，不新增业务字段或越权借用证据。"""
    module, fact, body = setup_case()
    cited = {"evidence_ids": [str(EVIDENCE)]}
    body.update(
        short_term={
            "thesis": "待复核。",
            "drivers": [{**cited, "detail": "待复核。"}],
            "invalidation": [{**cited, "condition": "待复核。"}],
        },
        long_term={
            "thesis": "待复核。",
            "drivers": [{**cited, "detail": "待复核。"}],
            "invalidation": [{**cited, "condition": "待复核。", "impact": "待复核。"}],
        },
        catalysts=[{**cited, "claim": "待复核。"}],
        risks_and_invalidation=[{**cited, "impact": "待复核。"}],
        factor_interpretations=[{**cited, "summary": "待复核。"}],
    )
    body["fact_refs"] = [{"target": target, "fact_id": fact.reference_id}]
    out = json.loads(
        module.render_structured_fact_references(json.dumps(body), (fact,), symbol="BTCUSDT")
    )
    current: object = out
    for part in target.split("."):
        if isinstance(current, list):
            current = cast(list[object], current)[int(part)]
        elif isinstance(current, dict):
            current = cast(dict[str, object], current)[part]
        else:
            raise AssertionError("目标应解析到既有段落")
    assert isinstance(current, str)
    assert current.endswith(fact.statement)
