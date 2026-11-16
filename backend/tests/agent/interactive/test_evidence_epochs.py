# 验证 T08 证据冻结服务：受治理公开证据端口、传输预算、时间边界、幂等与错误路径。
# 所有公开证据、策略版本、任务标识和用量均为合成值；不联网、不调用模型、不写业务库。
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.agent.interactive.adapters.research_evidence import (
    MarketEvidenceFactProjector,
    MarketResearchEvidencePort,
)
from app.agent_runs.attempts import (
    AttemptCategory,
    AttemptRequest,
    AttemptResult,
    AttemptStatus,
    StepAttempt,
)
from app.agent_runs.budget import BudgetLedger, BudgetLimits, BudgetStatus
from app.agent_runs.contracts import AgentRunError, RunInput, RunSnapshot, RunStatus
from app.agent_runs.evidence import (
    EVIDENCE_ACTION_SEQUENCE_BASE,
    MAX_EVIDENCE_TRANSPORT_CALLS,
    EvidenceCollection,
    EvidenceDraft,
    EvidenceRepository,
    EvidenceService,
    ResearchEvidencePort,
)
from app.agent_runs.ports import AgentRunReader
from app.agent_runs.segments import (
    EMPTY_TOOL_CATALOG_SHA256,
    ExecutionContext,
    RunFence,
)
from app.market.contracts import (
    Candle,
    CandleSeries,
    DataFreshness,
    FreshnessStatus,
    MarketDetail,
    MarketSummary,
    MarketTimeframe,
)
from app.market.gateway import PublicMarketGateway
from app.market.symbols import ResearchSymbol
from app.research.evidence import (
    EvidenceEpoch,
    EvidenceItem,
    EvidenceQuality,
    EvidenceUnavailableError,
)
from app.shared.agent_types import JsonObject, ProductKey, VersionRef, sha256_json

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
WORKSPACE_ID = uuid4()
RUN_ID = uuid4()
SEGMENT_ID = uuid4()
OWNER_ID = uuid4()
BUDGET_AUTHORIZATION_ID = uuid4()
STRATEGY_REF = VersionRef(version_id=uuid4(), sha256="a" * 64)


# 构造当前模式任务输入；不含账户、资金、订单或真实策略参数。
def _run_input(*, analysis_mode: str = "current") -> RunInput:
    return RunInput(
        request_id=uuid4(),
        product=ProductKey(
            venue="binance_usdm",
            symbol="BTCUSDT",
            settlement="USDT",
            kind="linear_perpetual",
        ),
        timeframes=(MarketTimeframe.H1, MarketTimeframe.H4),
        goal="合成公开行情研究",
        strategy=STRATEGY_REF,
        parameters={},
        analysis_mode=cast(Any, analysis_mode),
        as_of=NOW - timedelta(days=1) if analysis_mode == "historical" else None,
    )


# 构造运行中任务快照；取消标记由单个用例覆盖。
def _snapshot(
    *,
    analysis_mode: str = "current",
    cancel_requested_at: datetime | None = None,
) -> RunSnapshot:
    return RunSnapshot(
        run_id=RUN_ID,
        workspace_id=WORKSPACE_ID,
        thread_id=uuid4(),
        revision=1,
        status=RunStatus.RUNNING,
        state_version=1,
        input=_run_input(analysis_mode=analysis_mode),
        received_message_seq=0,
        applied_message_seq=0,
        created_at=NOW - timedelta(minutes=1),
        updated_at=NOW - timedelta(minutes=1),
        started_at=NOW - timedelta(seconds=30),
        cancel_requested_at=cancel_requested_at,
    )


# 服务端执行上下文只允许注入当前 worker 围栏和冻结引用。
def _context() -> ExecutionContext:
    return ExecutionContext(
        fence=RunFence(
            workspace_id=WORKSPACE_ID,
            run_id=RUN_ID,
            revision=1,
            segment_id=SEGMENT_ID,
            owner=OWNER_ID,
            lease_epoch=1,
        ),
        strategy_ref=STRATEGY_REF,
        tool_catalog_sha256=EMPTY_TOOL_CATALOG_SHA256,
        policy_version="interactive_planning_v1",
        budget_authorization_id=BUDGET_AUTHORIZATION_ID,
    )


# 合成公开证据草稿；内容刻意使用公开摘要而不是账户/资金字段。
def _draft(
    *,
    quality: EvidenceQuality = EvidenceQuality.VALID,
    observed_at: datetime = NOW,
    available_at: datetime | None = None,
    fetched_at: datetime = NOW,
    calculation_version: str | None = "market_detail_v1",
) -> EvidenceDraft:
    content: JsonObject = {"symbol": "BTCUSDT", "price": "106.2"}
    return EvidenceDraft(
        kind="market_detail",
        source="synthetic-public-source",
        observed_at=observed_at,
        available_at=available_at or observed_at,
        fetched_at=fetched_at,
        quality=quality,
        calculation_version=calculation_version,
        content=content,
    )


# 固定时钟任务读取替身；只返回单个当前运行快照。
class FakeRunReader:
    def __init__(self, snapshot: RunSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    async def get(self, workspace_id: UUID, run_id: UUID) -> RunSnapshot | None:
        self.calls += 1
        if workspace_id == self.snapshot.workspace_id and run_id == self.snapshot.run_id:
            return self.snapshot
        return None


# 公开证据端口替身；事件列表用于证明预算发送先于真实公开读取。
class FakeEvidencePort:
    def __init__(
        self,
        *,
        items: tuple[EvidenceDraft, ...] | None = None,
        error: Exception | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.items = items or (_draft(),)
        self.error = error
        self.events = events if events is not None else []
        self.calls: list[tuple[ProductKey, tuple[MarketTimeframe, ...], datetime]] = []

    def planned_transport_calls(self, timeframes: tuple[MarketTimeframe, ...]) -> int:
        return 1 + len(timeframes)

    async def collect(
        self,
        *,
        product: ProductKey,
        timeframes: tuple[MarketTimeframe, ...],
        analysis_as_of: datetime,
    ) -> EvidenceCollection:
        self.events.append("collect")
        self.calls.append((product, timeframes, analysis_as_of))
        if self.error is not None:
            raise self.error
        return EvidenceCollection(items=self.items)


# 证据仓储替身；只记录服务调用，不执行 SQL 或跨工作台读写。
class FakeEvidenceRepository:
    def __init__(self, existing: EvidenceEpoch | None = None) -> None:
        self.existing = existing
        self.saved: list[tuple[RunFence, EvidenceEpoch]] = []

    async def save_evidence(self, fence: RunFence, epoch: EvidenceEpoch) -> EvidenceEpoch:
        self.saved.append((fence, epoch))
        return epoch

    async def load_evidence(
        self,
        workspace_id: UUID,
        run_id: UUID,
        epoch_id: UUID,
    ) -> EvidenceEpoch | None:
        _ = (workspace_id, run_id, epoch_id)
        return self.existing

    async def load_latest_evidence(
        self,
        workspace_id: UUID,
        run_id: UUID,
        revision: int,
    ) -> EvidenceEpoch | None:
        _ = (workspace_id, run_id, revision)
        return self.existing

    async def count_evidence(
        self,
        workspace_id: UUID,
        run_id: UUID,
        revision: int,
    ) -> int:
        _ = (workspace_id, run_id, revision)
        return 1 if self.existing is not None else len(self.saved)


# 预算账本替身；按顺序记录预留/发送/结算，并可注入预算不足或结算失败。
class FakeBudget:
    def __init__(self, *, fail_reserve: bool = False, events: list[str]) -> None:
        self.fail_reserve = fail_reserve
        self.events = events
        self.requests: list[AttemptRequest] = []
        self.sent: list[UUID] = []
        self.results: list[tuple[UUID, AttemptResult]] = []

    async def reserve(self, fence: RunFence, request: AttemptRequest) -> StepAttempt:
        self.events.append("reserve")
        if self.fail_reserve:
            raise AgentRunError("budget_exhausted")
        self.requests.append(request)
        attempt_id = uuid4()
        return StepAttempt(
            attempt_id=attempt_id,
            step_id=uuid4(),
            run_id=fence.run_id,
            revision=fence.revision,
            segment_id=fence.segment_id,
            attempt_number=1,
            category=AttemptCategory.TRANSPORT,
            action_sequence=request.action_sequence,
            input_sha256=request.input_sha256,
            status=AttemptStatus.PREPARED,
            reserved_input_tokens=0,
            reserved_output_tokens=0,
            created_at=NOW,
        )

    async def mark_sent(self, fence: RunFence, attempt_id: UUID) -> None:
        _ = fence
        self.events.append("mark_sent")
        self.sent.append(attempt_id)

    async def settle(
        self,
        fence: RunFence,
        attempt_id: UUID,
        result: AttemptResult,
    ) -> None:
        _ = fence
        self.events.append("settle")
        self.results.append((attempt_id, result))

    async def status(self, fence: RunFence) -> BudgetStatus:
        _ = fence
        raise NotImplementedError

    async def record_activity(self, fence: RunFence, seconds: int) -> BudgetStatus:
        _ = (fence, seconds)
        raise NotImplementedError

    async def append_authorization(
        self,
        fence: RunFence,
        limits: BudgetLimits,
        *,
        authorization_ref: UUID,
        reason: str,
    ) -> BudgetStatus:
        _ = (fence, limits, authorization_ref, reason)
        raise NotImplementedError


# 构造服务并强制使用协议类型，避免测试替身被误当作生产 SQL 实现。
def _service(
    *,
    snapshot: RunSnapshot | None = None,
    port: FakeEvidencePort | None = None,
    budget: FakeBudget,
    repository: FakeEvidenceRepository,
) -> tuple[EvidenceService, FakeEvidencePort, FakeEvidenceRepository]:
    reader = FakeRunReader(snapshot or _snapshot())
    evidence_port = port or FakeEvidencePort()
    service = EvidenceService(
        run_reader=cast(AgentRunReader, reader),
        evidence_port=cast(ResearchEvidencePort, evidence_port),
        repository=cast(EvidenceRepository, repository),
        budget=cast(BudgetLedger, budget),
        clock=lambda: NOW,
    )
    return service, evidence_port, repository


# 正常冻结：逐次预留并发送累计传输，作为预先采集事实写入不可变 epoch。
@pytest.mark.asyncio
async def test_freeze_seals_epoch_and_accounts_for_each_planned_transport_read() -> None:
    events: list[str] = []
    budget = FakeBudget(events=events)
    port = FakeEvidencePort(events=events)
    repository = FakeEvidenceRepository()

    service, _, _ = _service(port=port, budget=budget, repository=repository)
    epoch = await service.freeze(_context())

    assert len(port.calls) == 1
    assert port.calls[0][1] == (MarketTimeframe.H1, MarketTimeframe.H4)
    assert [request.category for request in budget.requests] == [
        AttemptCategory.TRANSPORT,
        AttemptCategory.TRANSPORT,
        AttemptCategory.TRANSPORT,
    ]
    assert [request.action_sequence for request in budget.requests] == [
        EVIDENCE_ACTION_SEQUENCE_BASE,
        EVIDENCE_ACTION_SEQUENCE_BASE + 1,
        EVIDENCE_ACTION_SEQUENCE_BASE + 2,
    ]
    # 三个传输步骤先全部预留、提交发送，再真实读取；结算发生在证据保存之后。
    assert events[:7] == [
        "reserve",
        "reserve",
        "reserve",
        "mark_sent",
        "mark_sent",
        "mark_sent",
        "collect",
    ]
    assert events[7:] == ["settle", "settle", "settle"]
    assert epoch.analysis_as_of == NOW
    assert epoch.sealed_at == NOW
    assert epoch.items[0].quality is EvidenceQuality.VALID
    assert epoch.items[0].calculation_version == "market_detail_v1"
    assert repository.saved[0][1] == epoch
    assert all(result.status is AttemptStatus.SUCCEEDED for _, result in budget.results)
    for _, result in budget.results:
        assert result.result_ref is not None
        assert result.result_ref.artifact_id == epoch.epoch_id
        assert result.result_ref.sha256 == epoch.sha256


# 同一片段重复冻结：已保存 epoch 直接复用，不再读取公开源或消耗传输预算。
@pytest.mark.asyncio
async def test_existing_epoch_is_reused_without_new_public_read_or_budget() -> None:
    existing = EvidenceEpoch.seal(
        analysis_as_of=NOW,
        sealed_at=NOW,
        items=(
            EvidenceItem(
                evidence_id=uuid4(),
                kind="market_detail",
                source="synthetic-public-source",
                observed_at=NOW,
                available_at=NOW,
                fetched_at=NOW,
                payload_sha256=sha256_json({"symbol": "BTCUSDT"}),
                quality=EvidenceQuality.VALID,
                calculation_version="market_detail_v1",
                content={"symbol": "BTCUSDT"},
            ),
        ),
    )
    repository = FakeEvidenceRepository(existing=existing)
    events: list[str] = []
    budget = FakeBudget(events=events)
    port = FakeEvidencePort(events=events)

    service, _, _ = _service(port=port, budget=budget, repository=repository)
    epoch = await service.freeze(_context())

    assert epoch == existing
    assert port.calls == []
    assert events == []


# 显式刷新必须使用新的动作序号区段，避免与已提交证据步骤的幂等键冲突。
@pytest.mark.asyncio
async def test_refresh_allocates_new_action_sequence_band() -> None:
    existing = EvidenceEpoch.seal(
        analysis_as_of=NOW,
        sealed_at=NOW,
        items=(
            EvidenceItem(
                evidence_id=uuid4(),
                kind="market_detail",
                source="synthetic-public-source",
                observed_at=NOW,
                available_at=NOW,
                fetched_at=NOW,
                payload_sha256=sha256_json({"symbol": "BTCUSDT"}),
                quality=EvidenceQuality.VALID,
                content={"symbol": "BTCUSDT"},
            ),
        ),
    )
    repository = FakeEvidenceRepository(existing=existing)
    events: list[str] = []
    budget = FakeBudget(events=events)
    port = FakeEvidencePort(events=events)

    service, _, _ = _service(port=port, budget=budget, repository=repository)
    await service.freeze(_context(), refresh=True)

    assert budget.requests[0].action_sequence == (
        EVIDENCE_ACTION_SEQUENCE_BASE + MAX_EVIDENCE_TRANSPORT_CALLS
    )
    assert port.calls


# 历史模式没有可证明的历史公开源时拒绝，不把当前行情冒充历史截止值。
@pytest.mark.asyncio
async def test_historical_mode_is_rejected_without_collecting_current_data() -> None:
    events: list[str] = []
    budget = FakeBudget(events=events)
    port = FakeEvidencePort(events=events)
    service, _, _ = _service(
        snapshot=_snapshot(analysis_mode="historical"),
        port=port,
        budget=budget,
        repository=FakeEvidenceRepository(),
    )

    with pytest.raises(EvidenceUnavailableError) as raised:
        await service.freeze(_context())

    assert raised.value.code == "historical_evidence_unavailable"
    assert port.calls == []
    assert budget.requests == []


# 未来观测/抓取时间不得写进冻结证据；本轮读取已完成但结果不合格，预算按失败结算。
@pytest.mark.asyncio
async def test_future_evidence_times_are_rejected_before_persistence() -> None:
    events: list[str] = []
    budget = FakeBudget(events=events)
    port = FakeEvidencePort(
        items=(
            _draft(
                observed_at=NOW + timedelta(seconds=1),
                available_at=NOW + timedelta(seconds=1),
                fetched_at=NOW + timedelta(seconds=2),
            ),
        ),
        events=events,
    )
    repository = FakeEvidenceRepository()
    service, _, _ = _service(port=port, budget=budget, repository=repository)

    with pytest.raises(EvidenceUnavailableError) as raised:
        await service.freeze(_context())

    assert raised.value.code == "evidence_time_in_future"
    assert repository.saved == []
    assert all(result.status is AttemptStatus.FAILED for _, result in budget.results)


# 公开源已标记过期时保留 stale 质量，不能为了生成本次上下文改写为 valid。
@pytest.mark.asyncio
async def test_stale_quality_is_preserved_not_reclassified() -> None:
    events: list[str] = []
    budget = FakeBudget(events=events)
    port = FakeEvidencePort(items=(_draft(quality=EvidenceQuality.STALE),), events=events)
    service, _, _ = _service(port=port, budget=budget, repository=FakeEvidenceRepository())

    epoch = await service.freeze(_context())

    assert epoch.items[0].quality is EvidenceQuality.STALE


# 预算不足时必须在任何公开发送前停止；不能先读取再追认用量。
@pytest.mark.asyncio
async def test_budget_exhaustion_stops_before_public_read() -> None:
    events: list[str] = []
    budget = FakeBudget(fail_reserve=True, events=events)
    port = FakeEvidencePort(events=events)
    service, _, _ = _service(port=port, budget=budget, repository=FakeEvidenceRepository())

    with pytest.raises(AgentRunError) as raised:
        await service.freeze(_context())

    assert raised.value.code == "budget_exhausted"
    assert port.calls == []
    assert events == ["reserve"]


# 外部读取异常可能发生在请求已发出之后，按 unknown 保守保留预算且不保存半成品证据。
@pytest.mark.asyncio
async def test_collection_failure_settles_unknown_and_never_persists() -> None:
    events: list[str] = []
    budget = FakeBudget(events=events)
    port = FakeEvidencePort(error=RuntimeError("synthetic upstream failure"), events=events)
    repository = FakeEvidenceRepository()
    service, _, _ = _service(port=port, budget=budget, repository=repository)

    with pytest.raises(EvidenceUnavailableError) as raised:
        await service.freeze(_context())

    assert raised.value.code == "evidence_collection_failed"
    assert repository.saved == []
    assert all(result.status is AttemptStatus.UNKNOWN for _, result in budget.results)


# 已请求取消的运行不再发起公开读取；取消标记先于任何新外部调用生效。
@pytest.mark.asyncio
async def test_cancelled_run_is_not_collected() -> None:
    events: list[str] = []
    budget = FakeBudget(events=events)
    port = FakeEvidencePort(events=events)
    service, _, _ = _service(
        snapshot=_snapshot(cancel_requested_at=NOW - timedelta(seconds=1)),
        port=port,
        budget=budget,
        repository=FakeEvidenceRepository(),
    )

    with pytest.raises(AgentRunError) as raised:
        await service.freeze(_context())

    assert raised.value.code == "run_cancelling"
    assert port.calls == []


# 合成公开行情详情；时间关系满足 observed <= fetched，且 K 线已收盘。
def _market_detail(
    *,
    status: FreshnessStatus = FreshnessStatus.FRESH,
    candle_close_at: datetime | None = None,
) -> MarketDetail:
    close_at = candle_close_at or (NOW - timedelta(minutes=1))
    candle = Candle(
        symbol="BTCUSDT",
        timeframe=MarketTimeframe.H1,
        open_at=close_at - timedelta(hours=1),
        close_at=close_at,
        open_price=Decimal("105"),
        high_price=Decimal("107"),
        low_price=Decimal("104"),
        close_price=Decimal("106.2"),
        volume=Decimal("12.5"),
        observed_at=close_at,
        fetched_at=NOW,
    )
    return MarketDetail(
        summary=MarketSummary(
            symbol="BTCUSDT",
            price=Decimal("106.2"),
            change_24h=Decimal("0.5"),
            volume_24h=Decimal("1000"),
            funding_rate=Decimal("0.0001"),
            open_interest=Decimal("100"),
            freshness=DataFreshness(
                status=status,
                source="synthetic-public-source",
                observed_at=NOW - timedelta(minutes=2),
                fetched_at=NOW - timedelta(minutes=1),
            ),
        ),
        series=(CandleSeries(timeframe=MarketTimeframe.H1, candles=(candle,)),),
    )


# 公开行情网关替身；只返回固定详情并记录请求，不联网。
class FakeMarketGateway:
    def __init__(self, detail: MarketDetail) -> None:
        self.detail = detail
        self.calls: list[tuple[ResearchSymbol, tuple[MarketTimeframe, ...]]] = []

    async def get_market(
        self,
        symbol: ResearchSymbol,
        timeframes: tuple[MarketTimeframe, ...],
    ) -> MarketDetail:
        self.calls.append((symbol, timeframes))
        return self.detail

    async def get_summaries(self, symbols: tuple[ResearchSymbol, ...]) -> tuple[MarketSummary, ...]:
        _ = symbols
        raise NotImplementedError


# 适配器只读取固定公开行情并保留真实来源时间；质量/周期覆盖不完整时明确拒绝。
@pytest.mark.asyncio
async def test_market_evidence_port_preserves_times_and_quality() -> None:
    gateway = FakeMarketGateway(_market_detail())
    port = MarketResearchEvidencePort(cast(PublicMarketGateway, gateway))
    product = _run_input().product

    collection = await port.collect(
        product=product,
        timeframes=(MarketTimeframe.H1,),
        analysis_as_of=NOW,
    )

    assert port.planned_transport_calls((MarketTimeframe.H1,)) == 2
    assert gateway.calls == [("BTCUSDT", (MarketTimeframe.H1,))]
    item = collection.items[0]
    assert item.kind == "market_detail"
    assert item.quality is EvidenceQuality.VALID
    assert item.calculation_version == "market_detail_v1"
    assert item.observed_at == NOW - timedelta(minutes=2)
    assert item.fetched_at == NOW
    assert item.content is not None
    assert item.content["summary"]["symbol"] == "BTCUSDT"  # type: ignore[index]


# 来源已过期时保留 stale，不把旧摘要重新标成 valid。
@pytest.mark.asyncio
async def test_market_evidence_port_preserves_stale_source_quality() -> None:
    gateway = FakeMarketGateway(_market_detail(status=FreshnessStatus.STALE))
    port = MarketResearchEvidencePort(cast(PublicMarketGateway, gateway))

    collection = await port.collect(
        product=_run_input().product,
        timeframes=(MarketTimeframe.H1,),
        analysis_as_of=NOW,
    )

    assert collection.items[0].quality is EvidenceQuality.STALE


# 分析截止之后才收盘的 K 线不能进入冻结证据，即使网关已返回该序列。
@pytest.mark.asyncio
async def test_market_evidence_port_rejects_unclosed_candle() -> None:
    gateway = FakeMarketGateway(_market_detail(candle_close_at=NOW + timedelta(minutes=1)))
    port = MarketResearchEvidencePort(cast(PublicMarketGateway, gateway))

    with pytest.raises(EvidenceUnavailableError) as raised:
        await port.collect(
            product=_run_input().product,
            timeframes=(MarketTimeframe.H1,),
            analysis_as_of=NOW,
        )

    assert raised.value.code == "market_data_not_closed"


# 公开事实投影只包含行情字段和时点，不泄漏本地资金/仓位/杠杆字段。
def test_market_fact_projector_renders_public_values_without_financial_fields() -> None:
    item = EvidenceDraft(
        kind="market_detail",
        source="synthetic-public-source",
        observed_at=NOW - timedelta(minutes=2),
        available_at=NOW - timedelta(minutes=1),
        fetched_at=NOW,
        quality=EvidenceQuality.VALID,
        calculation_version="market_detail_v1",
        content=_market_detail().model_dump(mode="json"),
    ).to_item()

    text = MarketEvidenceFactProjector().project(item)

    assert text is not None
    assert "symbol=BTCUSDT" in text
    assert "timeframe=1h" in text
    assert "close=106.2" in text
    for key in ("available_margin", "position_notional", "leverage", "daily_loss"):
        assert key not in text


# 读取发生在请求时刻之后时，封存时刻必须重新采样，不能把正常 fetched_at 误判为未来证据。
@pytest.mark.asyncio
async def test_seal_time_is_sampled_after_public_read() -> None:
    events: list[str] = []
    budget = FakeBudget(events=events)
    port = FakeEvidencePort(
        items=(
            _draft(
                observed_at=NOW,
                available_at=NOW,
                fetched_at=NOW + timedelta(seconds=1),
            ),
        ),
        events=events,
    )
    times = iter((NOW, NOW + timedelta(seconds=2)))
    reader = FakeRunReader(_snapshot())
    service = EvidenceService(
        run_reader=cast(AgentRunReader, reader),
        evidence_port=cast(ResearchEvidencePort, port),
        repository=cast(EvidenceRepository, FakeEvidenceRepository()),
        budget=cast(BudgetLedger, budget),
        clock=lambda: next(times),
    )

    epoch = await service.freeze(_context())

    assert epoch.sealed_at == NOW + timedelta(seconds=2)
    assert epoch.analysis_as_of == NOW + timedelta(seconds=2)
    assert epoch.items[0].fetched_at == NOW + timedelta(seconds=1)


# 调用方不能把另一个任务的 EvidenceEpoch 塞入 ExecutionContext 绕过冻结/持久化。
@pytest.mark.asyncio
async def test_context_epoch_must_exist_in_current_run_storage() -> None:
    epoch = EvidenceEpoch.seal(
        analysis_as_of=NOW,
        sealed_at=NOW,
        items=(
            EvidenceItem(
                evidence_id=uuid4(),
                kind="market_detail",
                source="synthetic-public-source",
                observed_at=NOW,
                available_at=NOW,
                fetched_at=NOW,
                payload_sha256=sha256_json({"symbol": "BTCUSDT"}),
                quality=EvidenceQuality.VALID,
                content={"symbol": "BTCUSDT"},
            ),
        ),
    )
    events: list[str] = []
    service, _, _ = _service(
        port=FakeEvidencePort(events=events),
        budget=FakeBudget(events=events),
        repository=FakeEvidenceRepository(),
    )

    with pytest.raises(AgentRunError) as raised:
        await service.freeze(_context().model_copy(update={"evidence_epoch": epoch}))

    assert raised.value.code == "run_state_conflict"
