# 验证研究符号扩展与交易符号限制各自独立。
# 新增研究符号可进入研究请求，但不能扩大静态交易契约。
# 不支持的 ETF 专题返回明确原因而不伪造证据。
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from app.agent.factor_collection import collect_etf
from app.harness.contracts import HarnessRunKind, HarnessRunRequest
from app.market.contracts import Candle, ContractSymbol
from app.paper_trading.contracts import PaperAccount
from app.reports.contracts import AnalysisReportDraft
from app.strategy.contracts import TradeIntent


@pytest.mark.parametrize("model", (Candle, AnalysisReportDraft, HarnessRunRequest))
def test_research_contract_symbol_accepts_sol(model: type) -> None:
    adapter = TypeAdapter(model.model_fields["symbol"].rebuild_annotation())
    assert adapter.validate_python("SOLUSDT") == "SOLUSDT"


@pytest.mark.parametrize("model", (TradeIntent, PaperAccount))
def test_trading_contract_symbol_stays_restricted(model: type) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(model.model_fields["symbol"].rebuild_annotation()).validate_python("SOLUSDT")
    assert tuple(ContractSymbol) == (ContractSymbol.BTCUSDT, ContractSymbol.ETHUSDT)


def test_dynamic_harness_request_serializes_plain_symbol() -> None:
    request = HarnessRunRequest(
        run_id=uuid4(), kind=HarnessRunKind.MARKET_RESEARCH,
        symbol="SOLUSDT", requested_at=datetime.now(UTC),
    )
    assert request.model_dump(mode="json")["symbol"] == "SOLUSDT"


@pytest.mark.asyncio
async def test_unsupported_etf_has_exact_reason_without_evidence() -> None:
    topic, evidence = await collect_etf(None, symbol="SOLUSDT", as_of=datetime.now(UTC))
    assert topic.status == "missing"
    assert topic.limitations == ("当前数据源不支持",)
    assert topic.interpretation is None
    assert evidence is None
