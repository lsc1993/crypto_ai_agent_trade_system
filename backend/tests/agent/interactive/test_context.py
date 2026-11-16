# 验证 T08 上下文构建：精确策略、冻结证据、知识可得性、消息水位、配对裁剪和财务隔离。
# 使用合成任务/策略/知识/证据与异步替身，不联网、不调用模型/工具、不写入真实数据。
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.agent.interactive.context import (
    ContextBuilder,
    ContextBuildError,
    ContextHistory,
    ContextHistoryReader,
    ContextSummary,
    ContextUserMessage,
    ModelMessage,
    ModelTool,
    ModelToolCall,
    ToolTurn,
    encode_model_request,
)
from app.agent.interactive.context_budget import estimate_input
from app.agent_runs.contracts import RunInput, RunSnapshot, RunStatus
from app.agent_runs.evidence import EvidenceFactProjector
from app.agent_runs.messages import MessageKind
from app.agent_runs.ports import AgentRunReader
from app.agent_runs.segments import EMPTY_TOOL_CATALOG_SHA256, ExecutionContext, RunFence
from app.market.contracts import MarketTimeframe
from app.research.evidence import EvidenceEpoch, EvidenceItem, EvidenceQuality
from app.research.knowledge.contracts import (
    KnowledgeHit,
    KnowledgeIndexError,
    KnowledgeQuery,
    knowledge_text_sha256,
)
from app.research.knowledge.ports import KnowledgeIndex
from app.research.strategies.contracts import (
    StrategyCapability,
    StrategyDraft,
    StrategyKind,
    StrategyVersion,
)
from app.research.strategies.ports import StrategyCatalog
from app.shared.agent_types import (
    JsonObject,
    ProductKey,
    VersionRef,
    sha256_json,
)
from app.trade_planning.inputs import PlanningRefs

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
WORKSPACE_ID = uuid4()
RUN_ID = uuid4()
SEGMENT_ID = uuid4()
OWNER_ID = uuid4()
BUDGET_AUTHORIZATION_ID = uuid4()
POOL_ID = uuid4()

_PRIVATE_SENTINEL = "987654.32"
_FORBIDDEN_FINANCIAL_KEYS = (
    "available_margin",
    "availableMargin",
    "daily_loss_remaining",
    "dailyLossRemaining",
    "leverage",
    "position_notional",
    "positionNotional",
    "order_quantity",
    "orderQuantity",
)


# 生成一个参数 Schema 合法的技术策略版本；方法正文可按用例加长。
def _strategy(
    *,
    method_text: str = "价格突破结构后，等待回踩确认并设置结构止损。",
    supported_timeframes: tuple[MarketTimeframe, ...] = (
        MarketTimeframe.H1,
        MarketTimeframe.H4,
        MarketTimeframe.D1,
    ),
) -> StrategyVersion:
    draft = StrategyDraft(
        draft_id=uuid4(),
        strategy_id=uuid4(),
        name="合成技术突破策略",
        method_text=method_text,
        kind=StrategyKind.SINGLE,
        parameter_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "minimum_reward_risk": {
                    "type": "decimal",
                    "minimum": "1.5",
                    "maximum": "10",
                }
            },
            "required": ["minimum_reward_risk"],
        },
        supported_symbols=("BTCUSDT",),
        supported_timeframes=supported_timeframes,
        warmup_candles=200,
        evaluator_id="technical_breakout_v1",
        capabilities=(
            StrategyCapability.RESEARCH,
            StrategyCapability.PRICE_CANDIDATE,
            StrategyCapability.MANUAL_PLANNING,
        ),
        risk_notes="止损触发不保证成交；计划必须经过确定性风险检查。",
    )
    return StrategyVersion.from_draft(draft, published_at=NOW, state_version=1)


# 任务输入包含本地资料引用，但不包含金额、仓位、杠杆或订单值。
def _run_input(
    strategy: StrategyVersion,
    *,
    analysis_mode: str = "current",
    goal: str = "分析 BTC 当前结构并准备手动计划",
) -> RunInput:
    planning = PlanningRefs(
        profile=VersionRef(version_id=uuid4(), sha256="b" * 64),
        policy=VersionRef(version_id=uuid4(), sha256="c" * 64),
        venue_rules=VersionRef(version_id=uuid4(), sha256="d" * 64),
        costs=VersionRef(version_id=uuid4(), sha256="e" * 64),
        pool_id=POOL_ID,
        pool_generation=1,
    )
    return RunInput(
        request_id=uuid4(),
        product=ProductKey(
            venue="binance_usdm",
            symbol="BTCUSDT",
            settlement="USDT",
            kind="linear_perpetual",
        ),
        timeframes=(MarketTimeframe.H1, MarketTimeframe.H4, MarketTimeframe.D1),
        goal=goal,
        strategy=strategy.ref,
        parameters={"minimum_reward_risk": "1.5"},
        planning=planning,
        analysis_mode=cast(Any, analysis_mode),
        as_of=NOW - timedelta(days=1) if analysis_mode == "historical" else None,
    )


# 构造运行中快照；已应用水位和已记录水位由用例指定。
def _snapshot(
    strategy: StrategyVersion,
    *,
    analysis_mode: str = "current",
    applied_message_seq: int = 0,
    received_message_seq: int = 0,
    goal: str = "分析 BTC 当前结构并准备手动计划",
) -> RunSnapshot:
    return RunSnapshot(
        run_id=RUN_ID,
        workspace_id=WORKSPACE_ID,
        thread_id=uuid4(),
        revision=1,
        status=RunStatus.RUNNING,
        state_version=1,
        input=_run_input(strategy, analysis_mode=analysis_mode, goal=goal),
        received_message_seq=received_message_seq,
        applied_message_seq=applied_message_seq,
        created_at=NOW - timedelta(minutes=5),
        updated_at=NOW - timedelta(minutes=1),
        started_at=NOW - timedelta(seconds=30),
    )


# 服务端上下文只携带当前围栏、策略和空工具目录指纹（T09 才登记工具）。
def _context(
    strategy: StrategyVersion,
    *,
    tool_catalog_sha256: str = EMPTY_TOOL_CATALOG_SHA256,
) -> ExecutionContext:
    return ExecutionContext(
        fence=RunFence(
            workspace_id=WORKSPACE_ID,
            run_id=RUN_ID,
            revision=1,
            segment_id=SEGMENT_ID,
            owner=OWNER_ID,
            lease_epoch=1,
        ),
        strategy_ref=strategy.ref,
        tool_catalog_sha256=tool_catalog_sha256,
        policy_version="interactive_planning_v1",
        budget_authorization_id=BUDGET_AUTHORIZATION_ID,
    )


# 合成冻结证据；内容只含公开市场字段，不含用户财务资料。
def _evidence(
    *,
    analysis_as_of: datetime = NOW,
    sealed_at: datetime | None = None,
    quality: EvidenceQuality = EvidenceQuality.VALID,
    evidence_id: UUID | None = None,
) -> EvidenceEpoch:
    content: JsonObject = {"symbol": "BTCUSDT", "price": "106.2"}
    item = EvidenceItem(
        evidence_id=evidence_id or uuid4(),
        kind="market_detail",
        source="synthetic-public-source",
        observed_at=analysis_as_of,
        available_at=analysis_as_of,
        fetched_at=sealed_at or analysis_as_of,
        payload_sha256=sha256_json(content),
        quality=quality,
        calculation_version="market_detail_v1",
        content=content,
    )
    return EvidenceEpoch.seal(
        analysis_as_of=analysis_as_of,
        sealed_at=sealed_at or analysis_as_of,
        items=(item,),
    )


# 任务读取替身；只返回一个当前运行快照。
class FakeRunReader:
    def __init__(self, snapshot: RunSnapshot) -> None:
        self.snapshot = snapshot

    async def get(self, workspace_id: UUID, run_id: UUID) -> RunSnapshot | None:
        if workspace_id == self.snapshot.workspace_id and run_id == self.snapshot.run_id:
            return self.snapshot
        return None


# 策略目录替身：记录精确版本请求，并返回预先构造的已发布版本。
class FakeStrategyCatalog:
    def __init__(self, strategy: StrategyVersion) -> None:
        self.strategy = strategy
        self.calls: list[tuple[UUID, VersionRef]] = []

    async def get_published(self, workspace_id: UUID, ref: VersionRef) -> StrategyVersion:
        self.calls.append((workspace_id, ref))
        return self.strategy

    async def publish(self, *args: Any, **kwargs: Any) -> StrategyVersion:
        raise NotImplementedError

    async def create_draft(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def update_draft(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def list_versions(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def archive(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError


# 知识检索替身：记录查询并返回固定命中或稳定错误；不执行 SQL。
class FakeKnowledgeIndex:
    def __init__(
        self,
        hits: tuple[KnowledgeHit, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.hits = hits
        self.error = error
        self.queries: list[KnowledgeQuery] = []

    async def search(self, workspace_id: UUID, query: KnowledgeQuery) -> tuple[KnowledgeHit, ...]:
        _ = workspace_id
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return self.hits

    async def import_text(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def publish(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def archive(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError

    async def list_versions(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


# 历史读取替身：模拟已提交消息、旧摘要和成对工具轮次。
class FakeHistoryReader:
    def __init__(self, history: ContextHistory | None = None) -> None:
        self.history = history or ContextHistory()
        self.calls: list[tuple[RunFence, int]] = []

    async def load(self, fence: RunFence, *, applied_seq: int) -> ContextHistory:
        self.calls.append((fence, applied_seq))
        return self.history


# 证据事实投影替身：只返回安全公开文本，未知类型返回 None。
class FakeEvidenceProjector:
    def project(self, item: EvidenceItem) -> str | None:
        if item.kind != "market_detail":
            return None
        return "公开行情事实：symbol=BTCUSDT price=106.2（合成公开数据）"


# 空工具目录；T08 不提供真实工具，T09/T11 再注入登记目录。
class EmptyToolCatalog:
    async def authorized(self, context: ExecutionContext) -> tuple[ModelTool, ...]:
        _ = context
        return ()


# 构造知识命中；正文、来源与时间均为合成值。
def _hit(
    *,
    text: str = "突破策略要求在结构确认后设置保护止损。",
    chunk_id: UUID | None = None,
    score: int = 5,
    first_available_at: datetime = NOW - timedelta(days=10),
    published_at: datetime = NOW - timedelta(days=9),
) -> KnowledgeHit:
    return KnowledgeHit(
        document_id=uuid4(),
        version_ref=VersionRef(version_id=uuid4(), sha256="f" * 64),
        chunk_id=chunk_id or uuid4(),
        chunk_index=0,
        title="合成方法文档",
        text=text,
        source="synthetic-method-source",
        scope="method",
        first_available_at=first_available_at,
        published_at=published_at,
        chunk_sha256=knowledge_text_sha256(text),
        score=score,
    )


# 构造成对工具轮次：assistant tool_call 后必须紧跟同 call_id 的 tool 结果。
def _tool_turn(*, turn_id: UUID | None = None, content_size: int = 20) -> ToolTurn:
    call_id = f"call-{uuid4()}"
    return ToolTurn(
        turn_id=turn_id or uuid4(),
        completed_at=NOW,
        messages=(
            ModelMessage(
                role="assistant",
                content=None,
                tool_calls=(ModelToolCall(call_id=call_id, name="get_market", arguments={}),),
            ),
            ModelMessage(role="tool", content="r" * content_size, tool_call_id=call_id),
        ),
    )


# 构造上下文构建器；默认为当前模式、空知识、空历史、空工具目录。
def _builder(
    *,
    snapshot: RunSnapshot,
    strategy: StrategyVersion,
    knowledge: FakeKnowledgeIndex | None = None,
    history: FakeHistoryReader | None = None,
    tool_catalog: EmptyToolCatalog | None = None,
    max_input_units: int | None = None,
) -> ContextBuilder:
    knowledge_index = knowledge or FakeKnowledgeIndex()
    arguments: dict[str, Any] = {}
    if max_input_units is not None:
        arguments["max_input_units"] = max_input_units
    return ContextBuilder(
        run_reader=cast(AgentRunReader, FakeRunReader(snapshot)),
        strategies=cast(StrategyCatalog, FakeStrategyCatalog(strategy)),
        knowledge=cast(KnowledgeIndex, knowledge_index),
        history=cast(ContextHistoryReader, history or FakeHistoryReader()),
        evidence_projector=cast(EvidenceFactProjector, FakeEvidenceProjector()),
        tool_catalog=tool_catalog or EmptyToolCatalog(),
        clock=lambda: NOW,
        **arguments,
    )


# 序列化模型上下文用于敏感值/字段扫描；只比较 JSON 文本，不解释语义。
def _serialized(model_context: Any) -> str:
    return json.dumps(model_context.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)


# 无 RAG 命中时仍必须保留用户选择的精确策略和参数，不能回退其他策略。
@pytest.mark.asyncio
async def test_exact_strategy_is_loaded_and_preserved_without_rag_hits() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy)
    builder = _builder(snapshot=snapshot, strategy=strategy)

    model_context = await builder.build(_context(strategy), _evidence(), applied_seq=0)

    assert model_context.manifest.strategy_ref == strategy.ref
    assert "合成技术突破策略" in _serialized(model_context)
    assert "minimum_reward_risk" in _serialized(model_context)
    assert model_context.manifest.knowledge_refs == ()
    assert "knowledge_no_hits" in model_context.manifest.limitations
    assert model_context.manifest.applied_seq == 0


# 规划资料只以版本引用/池代次进入上下文；金额、仓位和杠杆字段不得出现在模型投影。
@pytest.mark.asyncio
async def test_private_financial_values_and_fields_never_enter_model_context() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy)
    builder = _builder(snapshot=snapshot, strategy=strategy)

    model_context = await builder.build(_context(strategy), _evidence(), applied_seq=0)
    serialized = _serialized(model_context)

    assert _PRIVATE_SENTINEL not in serialized
    for key in _FORBIDDEN_FINANCIAL_KEYS:
        assert key not in serialized
    assert str(snapshot.input.planning.profile.version_id) in serialized  # type: ignore[union-attr]


# 新消息必须全部进入上下文；缺一条已记录消息时拒绝构建，不能用旧上下文冒充完成。
@pytest.mark.asyncio
async def test_new_messages_must_all_be_present_before_advancing_watermark() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy, applied_message_seq=1, received_message_seq=3)
    history = FakeHistoryReader(
        ContextHistory(
            messages=(
                ContextUserMessage(sequence=1, kind=MessageKind.TEXT, text="旧消息"),
                ContextUserMessage(sequence=2, kind=MessageKind.TEXT, text="新增一"),
                ContextUserMessage(sequence=3, kind=MessageKind.TEXT, text="新增二"),
            )
        )
    )
    builder = _builder(snapshot=snapshot, strategy=strategy, history=history)

    model_context = await builder.build(_context(strategy), _evidence(), applied_seq=3)
    serialized = _serialized(model_context)

    assert model_context.manifest.applied_seq == 3
    assert 2 in model_context.manifest.message_sequences
    assert 3 in model_context.manifest.message_sequences
    assert "新增一" in serialized
    assert "新增二" in serialized

    missing = _builder(
        snapshot=snapshot,
        strategy=strategy,
        history=FakeHistoryReader(
            ContextHistory(
                messages=(
                    ContextUserMessage(sequence=1, kind=MessageKind.TEXT, text="旧消息"),
                    ContextUserMessage(sequence=2, kind=MessageKind.TEXT, text="新增一"),
                )
            )
        ),
    )
    with pytest.raises(ContextBuildError) as raised:
        await missing.build(_context(strategy), _evidence(), applied_seq=3)
    assert raised.value.code == "invalid_message_watermark"


# 没有当前 epoch 证据引用的旧摘要不能变成新事实；原文不进入消息，省略原因可审计。
@pytest.mark.asyncio
async def test_summary_without_current_evidence_is_omitted() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy)
    summary_text = "旧摘要声称价格已经突破但缺少当前证据。"
    history = FakeHistoryReader(
        ContextHistory(
            summaries=(
                ContextSummary(
                    summary_id=uuid4(),
                    text=summary_text,
                    evidence_ids=(uuid4(),),
                    created_at=NOW - timedelta(hours=2),
                ),
            )
        )
    )
    builder = _builder(snapshot=snapshot, strategy=strategy, history=history)

    model_context = await builder.build(_context(strategy), _evidence(), applied_seq=0)

    assert summary_text not in _serialized(model_context)
    assert any(
        item.kind == "summary" and item.reason == "unverified_summary"
        for item in model_context.manifest.omitted
    )


# 未来生成的摘要不能当作当前可重建观点；即使引用证据属于当前 epoch 也省略。
@pytest.mark.asyncio
async def test_future_summary_is_not_used_as_current_context() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy)
    evidence = _evidence()
    summary_text = "未来摘要不应进入当前上下文。"
    history = FakeHistoryReader(
        ContextHistory(
            summaries=(
                ContextSummary(
                    summary_id=uuid4(),
                    text=summary_text,
                    evidence_ids=tuple(item.evidence_id for item in evidence.items),
                    created_at=NOW + timedelta(minutes=1),
                ),
            )
        )
    )
    builder = _builder(snapshot=snapshot, strategy=strategy, history=history)

    model_context = await builder.build(_context(strategy), evidence, applied_seq=0)

    assert summary_text not in _serialized(model_context)
    assert any(
        item.kind == "summary" and item.reason == "unverified_summary"
        for item in model_context.manifest.omitted
    )


# 调用方传入的 ExecutionContext 证据与 build 参数不一致时拒绝，避免混用不同 epoch。
@pytest.mark.asyncio
async def test_context_evidence_epoch_must_match_build_argument() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy)
    builder = _builder(snapshot=snapshot, strategy=strategy)
    other = _evidence(analysis_as_of=NOW - timedelta(minutes=1))

    with pytest.raises(ContextBuildError) as raised:
        await builder.build(
            _context(strategy).model_copy(update={"evidence_epoch": other}),
            _evidence(),
            applied_seq=0,
        )

    assert raised.value.code == "evidence_epoch_mismatch"


# 工具历史裁剪只能整轮丢弃，不能留下没有 assistant tool_call 的孤立 tool 结果。
@pytest.mark.asyncio
async def test_tool_trimming_keeps_complete_call_result_pairs() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy)
    single_turn = _tool_turn(content_size=1_200)
    single_builder = _builder(
        snapshot=snapshot,
        strategy=strategy,
        history=FakeHistoryReader(ContextHistory(tool_turns=(single_turn,))),
    )
    single_context = await single_builder.build(_context(strategy), _evidence(), applied_seq=0)
    two_turn_builder = _builder(
        snapshot=snapshot,
        strategy=strategy,
        history=FakeHistoryReader(
            ContextHistory(
                tool_turns=(
                    _tool_turn(content_size=1_200),
                    _tool_turn(content_size=1_200),
                )
            )
        ),
        max_input_units=single_context.input_reservation,
    )

    model_context = await two_turn_builder.build(_context(strategy), _evidence(), applied_seq=0)

    tool_messages = [message for message in model_context.messages if message.role == "tool"]
    assistant_calls = [
        call
        for message in model_context.messages
        if message.role == "assistant"
        for call in message.tool_calls
    ]
    assert len(tool_messages) == len(assistant_calls) == 1
    assert tool_messages[0].tool_call_id == assistant_calls[0].call_id
    assert any(
        item.kind == "tool_turn" and item.reason == "input_budget"
        for item in model_context.manifest.omitted
    )


# 历史模式必须把知识检索限定在声明的截至时刻，且冻结证据不能晚于该时刻。
@pytest.mark.asyncio
async def test_historical_context_uses_declared_as_of_for_knowledge() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy, analysis_mode="historical")
    knowledge = FakeKnowledgeIndex(hits=(_hit(),))
    builder = _builder(snapshot=snapshot, strategy=strategy, knowledge=knowledge)
    evidence = _evidence(analysis_as_of=NOW - timedelta(days=2))

    model_context = await builder.build(_context(strategy), evidence, applied_seq=0)

    assert knowledge.queries[0].as_of == snapshot.input.as_of
    assert model_context.manifest.historical_as_of == snapshot.input.as_of
    assert model_context.manifest.analysis_mode == "historical"


# 历史模式下，分析截止之后才首次可得的资料不能进入旧截至上下文。
@pytest.mark.asyncio
async def test_historical_context_filters_later_available_knowledge() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy, analysis_mode="historical")
    later = _hit(
        text="后来才发布的方法材料。",
        first_available_at=NOW,
        published_at=NOW,
    )
    knowledge = FakeKnowledgeIndex(hits=(later,))
    builder = _builder(snapshot=snapshot, strategy=strategy, knowledge=knowledge)
    evidence = _evidence(analysis_as_of=NOW - timedelta(days=2))

    model_context = await builder.build(_context(strategy), evidence, applied_seq=0)

    assert later.text not in _serialized(model_context)
    assert "knowledge_filtered" in model_context.manifest.limitations
    assert "合成技术突破策略" in _serialized(model_context)


# 未来封存的证据不能用于当前决策；服务端时钟是唯一权威。
@pytest.mark.asyncio
async def test_future_evidence_epoch_is_rejected() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy)
    builder = _builder(snapshot=snapshot, strategy=strategy)
    evidence = _evidence(analysis_as_of=NOW, sealed_at=NOW + timedelta(minutes=1))

    with pytest.raises(ContextBuildError) as raised:
        await builder.build(_context(strategy), evidence, applied_seq=0)

    assert raised.value.code == "evidence_from_future"


# 过期证据必须作为限制暴露，不能悄悄按当前事实使用，也不改回原始截止时间。
@pytest.mark.asyncio
async def test_stale_evidence_is_marked_as_limitation() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy)
    builder = _builder(snapshot=snapshot, strategy=strategy)
    stale = _evidence(
        analysis_as_of=NOW - timedelta(minutes=20),
        quality=EvidenceQuality.STALE,
    )

    model_context = await builder.build(_context(strategy), stale, applied_seq=0)

    assert model_context.manifest.analysis_as_of == stale.analysis_as_of
    assert "evidence_stale" in model_context.manifest.limitations
    assert "evidence_quality_stale" in model_context.manifest.limitations


# 目录返回的版本与所选引用不一致时必须 fail-closed，不能静默换用另一个策略。
@pytest.mark.asyncio
async def test_strategy_version_mismatch_fails_closed() -> None:
    strategy = _strategy()
    other = _strategy(method_text="另一个不应被采用的策略。")
    snapshot = _snapshot(strategy)
    builder = _builder(snapshot=snapshot, strategy=other)

    with pytest.raises(ContextBuildError) as raised:
        await builder.build(_context(strategy), _evidence(), applied_seq=0)

    assert raised.value.code == "strategy_version_mismatch"


# 必需策略正文本身放不下单次预算时停止并要求更小范围，而不是截断策略或扩大窗口。
@pytest.mark.asyncio
async def test_required_strategy_that_exceeds_budget_stops_context() -> None:
    strategy = _strategy(method_text="策略正文" * 5_000)
    snapshot = _snapshot(strategy)
    builder = _builder(snapshot=snapshot, strategy=strategy, max_input_units=8_000)

    with pytest.raises(ContextBuildError) as raised:
        await builder.build(_context(strategy), _evidence(), applied_seq=0)

    assert raised.value.code == "context_budget_exceeded"


# 知识检索失败不能丢掉已选策略；只记录稳定限制并继续构建。
@pytest.mark.asyncio
async def test_knowledge_unavailable_preserves_strategy_and_reports_limitation() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy)
    knowledge = FakeKnowledgeIndex(error=KnowledgeIndexError("synthetic index unavailable"))
    builder = _builder(snapshot=snapshot, strategy=strategy, knowledge=knowledge)

    model_context = await builder.build(_context(strategy), _evidence(), applied_seq=0)

    assert model_context.manifest.strategy_ref == strategy.ref
    assert "knowledge_unavailable" in model_context.manifest.limitations
    assert "合成技术突破策略" in _serialized(model_context)


# 重复命中块按 chunk_id 去重，不能通过重复注入放大上下文或绕过预算。
@pytest.mark.asyncio
async def test_duplicate_knowledge_hits_are_deduplicated() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy)
    hit = _hit()
    knowledge = FakeKnowledgeIndex(hits=(hit, hit))
    builder = _builder(snapshot=snapshot, strategy=strategy, knowledge=knowledge)

    model_context = await builder.build(_context(strategy), _evidence(), applied_seq=0)

    assert model_context.manifest.knowledge_chunk_ids == (hit.chunk_id,)
    assert _serialized(model_context).count(hit.text) == 1


# 工具目录指纹与注入目录不一致时拒绝，避免模型看到未登记/变更后的工具 Schema。
@pytest.mark.asyncio
async def test_tool_catalog_fingerprint_mismatch_is_rejected() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy)
    builder = _builder(snapshot=snapshot, strategy=strategy)

    with pytest.raises(ContextBuildError) as raised:
        await builder.build(
            _context(strategy, tool_catalog_sha256="b" * 64),
            _evidence(),
            applied_seq=0,
        )

    assert raised.value.code == "tool_catalog_mismatch"


# 输入预留必须能由实际编码请求复算，不能用模型或供应商自报值。
@pytest.mark.asyncio
async def test_input_reservation_matches_encoded_request() -> None:
    strategy = _strategy()
    snapshot = _snapshot(strategy)
    builder = _builder(snapshot=snapshot, strategy=strategy)

    model_context = await builder.build(_context(strategy), _evidence(), applied_seq=0)
    encoded = encode_model_request(model_context.messages, model_context.tools)

    assert model_context.input_reservation == len(encoded) + 4_096
    assert model_context.input_reservation == estimate_input(encoded)
    assert model_context.manifest.input_reservation == model_context.input_reservation


# 知识查询必须受固定词项上限约束；用户长目标不能生成无界/非法的检索请求。
@pytest.mark.asyncio
async def test_knowledge_query_is_bounded_to_fixed_term_limit() -> None:
    strategy = _strategy()
    snapshot = _snapshot(
        strategy,
        goal=" ".join(f"word{index}" for index in range(200)),
    )
    knowledge = FakeKnowledgeIndex()
    builder = _builder(snapshot=snapshot, strategy=strategy, knowledge=knowledge)

    await builder.build(_context(strategy), _evidence(), applied_seq=0)

    assert knowledge.queries
    assert 1 <= len(knowledge.queries[0].terms) <= 64
