import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.market.contracts import ContractSymbol, MarketDataUnavailableError
from app.market.etf_flows import FARSIDE_BASE_URL, FarsideEtfFlowGateway

NOW = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
BTC_TICKERS = (
    "IBIT",
    "FBTC",
    "BITB",
    "ARKB",
    "BTCO",
    "EZBC",
    "BRRR",
    "HODL",
    "BTCW",
    "MSBT",
    "GBTC",
    "BTC",
)


def _actual_shape_page(
    *rows: tuple[str, ...],
    tickers: tuple[str, ...] = BTC_TICKERS,
    trailing_ticker_cell: str | None = None,
) -> str:
    logos = "".join(f'<td><img alt="{ticker} issuer"></td>' for ticker in tickers)
    ticker_cells = "".join(f"<td>{ticker}</td>" for ticker in tickers)
    ticker_tail = "" if trailing_ticker_cell is None else f"<td>{trailing_ticker_cell}</td>"
    fee_cells = "".join("<td>0.25%</td>" for _ in tickers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"""
        <html><body><h1>Bitcoin ETF Flow (US$m)</h1><table>
          <tr><td>&nbsp;</td>{logos}<td>Total</td></tr>
          <tr><td>&nbsp;</td>{ticker_cells}{ticker_tail}</tr>
          <tr><td>Fee</td>{fee_cells}</tr>
          {body}
        </table></body></html>
    """


def _row(label: str, values: tuple[str, ...], total: str) -> tuple[str, ...]:
    return (label, *values, total)


def _gateway(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    base_url: str = FARSIDE_BASE_URL,
    follow_redirects: bool = False,
) -> tuple[httpx.AsyncClient, FarsideEtfFlowGateway]:
    client = httpx.AsyncClient(
        base_url=base_url,
        follow_redirects=follow_redirects,
        transport=httpx.MockTransport(handler),
    )
    return client, FarsideEtfFlowGateway(client=client, clock=lambda: NOW)


@pytest.mark.asyncio
async def test_collect_parses_real_header_shape_and_preserves_missing_zero_and_negative() -> None:
    requests: list[httpx.Request] = []
    complete_values = ("1.0", *("0.0" for _ in range(11)))
    incomplete_values = ("(12.5)", "-", *("0.0" for _ in range(10)))
    html = _actual_shape_page(
        _row("Seed", tuple("0.0" for _ in range(12)), "0.0"),
        _row("03 Sep 2026", complete_values, "1.0"),
        _row("04 Sep 2026", incomplete_values, "(12.5)"),
        _row("Total", tuple("0.0" for _ in range(12)), "(11.5)"),
        _row("Average", tuple("0.0" for _ in range(12)), "0.0"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=html)

    client, gateway = _gateway(handler)
    async with client:
        snapshot = await gateway.collect(ContractSymbol.BTCUSDT, as_of=NOW)

    assert snapshot.symbol is ContractSymbol.BTCUSDT
    assert snapshot.fetched_at == NOW
    assert snapshot.source_url == "https://farside.co.uk/btc/"
    assert [day.trading_date.isoformat() for day in snapshot.days] == [
        "2026-09-03",
        "2026-09-04",
    ]
    assert snapshot.days[-1].funds["IBIT"] == Decimal("-12500000")
    assert snapshot.days[-1].funds["FBTC"] is None
    assert snapshot.days[-1].funds["BITB"] == Decimal("0")
    assert snapshot.days[-1].total_net_flow_usd == Decimal("-12500000")
    assert snapshot.days[-1].complete is False
    assert requests[0].url == httpx.URL("https://farside.co.uk/btc/")


@pytest.mark.asyncio
async def test_collect_uses_the_eth_path_and_discovers_its_current_fund_columns() -> None:
    tickers = ("ETHA", "ETHB", "FETH", "ETHW", "TETH", "ETHV", "QETH", "EZET", "ETHE", "ETH")
    html = _actual_shape_page(
        _row("04 Sep 2026", tuple("0.0" for _ in tickers), "0.0"),
        tickers=tickers,
    )
    client, gateway = _gateway(lambda _: httpx.Response(200, text=html))
    async with client:
        snapshot = await gateway.collect(ContractSymbol.ETHUSDT, as_of=NOW)

    assert snapshot.source_url == "https://farside.co.uk/eth/"
    assert tuple(snapshot.days[0].funds) == tickers


@pytest.mark.asyncio
async def test_collect_accepts_an_empty_total_header_cell_used_by_the_live_farside_table() -> None:
    html = _actual_shape_page(
        _row("04 Sep 2026", tuple("0.0" for _ in BTC_TICKERS), "0.0"),
        trailing_ticker_cell="",
    )
    client, gateway = _gateway(lambda _: httpx.Response(200, text=html))

    async with client:
        snapshot = await gateway.collect(ContractSymbol.BTCUSDT, as_of=NOW)

    assert snapshot.days[0].trading_date.isoformat() == "2026-09-04"
    assert tuple(snapshot.days[0].funds) == BTC_TICKERS


@pytest.mark.asyncio
async def test_collect_sends_the_farside_compatibility_user_agent() -> None:
    requests: list[httpx.Request] = []
    html = _actual_shape_page(_row("04 Sep 2026", tuple("0.0" for _ in range(12)), "0.0"))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=html)

    client, gateway = _gateway(handler)
    async with client:
        await gateway.collect(ContractSymbol.BTCUSDT, as_of=NOW)

    assert requests[0].headers["user-agent"] == (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )


@pytest.mark.asyncio
async def test_collect_preserves_incomplete_current_but_excludes_future_new_york_rows() -> None:
    missing = ("-", *("0.0" for _ in range(11)))
    html = _actual_shape_page(
        _row("04 Sep 2026", tuple("0.0" for _ in range(12)), "0.0"),
        _row("06 Sep 2026", missing, "0.0"),
        _row("07 Sep 2026", missing, "0.0"),
    )
    client, gateway = _gateway(lambda _: httpx.Response(200, text=html))
    async with client:
        snapshot = await gateway.collect(ContractSymbol.BTCUSDT, as_of=NOW)

    assert [day.trading_date.isoformat() for day in snapshot.days] == [
        "2026-09-04",
        "2026-09-06",
    ]
    assert snapshot.days[-1].complete is False


@pytest.mark.asyncio
async def test_collect_returns_only_the_latest_fifteen_rows() -> None:
    rows = tuple(
        _row(f"{day:02d} Aug 2026", tuple("0.0" for _ in range(12)), "0.0") for day in range(1, 21)
    )
    client, gateway = _gateway(lambda _: httpx.Response(200, text=_actual_shape_page(*rows)))
    async with client:
        snapshot = await gateway.collect(ContractSymbol.BTCUSDT, as_of=NOW)

    assert len(snapshot.days) == 15
    assert snapshot.days[0].trading_date.isoformat() == "2026-08-06"
    assert snapshot.days[-1].trading_date.isoformat() == "2026-08-20"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "html",
    [
        "<html><table><tr><td>nothing useful</td></tr></table></html>",
        _actual_shape_page(_row("04 Sep 2026", ("bad", *("0.0" for _ in range(11))), "0.0")),
        _actual_shape_page(_row("04 Sep 2026", tuple("0.0" for _ in range(12)), "5.0")),
        _actual_shape_page(
            _row("04 Sep 2026", tuple("0.0" for _ in range(12)), "0.0"),
            _row("04 Sep 2026", ("1.0", *("0.0" for _ in range(11))), "1.0"),
        ),
    ],
    ids=["empty-table", "malformed-value", "mismatched-total", "conflicting-date"],
)
async def test_collect_rejects_invalid_tables(html: str) -> None:
    client, gateway = _gateway(lambda _: httpx.Response(200, text=html))
    async with client:
        with pytest.raises(MarketDataUnavailableError) as error:
            await gateway.collect(ContractSymbol.BTCUSDT, as_of=NOW)

    assert error.value.code == "market_data_invalid_response"


@pytest.mark.asyncio
async def test_collect_rejects_a_signed_value_inside_parentheses() -> None:
    values = ("(-12.5)", *("0.0" for _ in range(11)))
    html = _actual_shape_page(_row("04 Sep 2026", values, "12.5"))
    client, gateway = _gateway(lambda _: httpx.Response(200, text=html))
    async with client:
        with pytest.raises(MarketDataUnavailableError) as error:
            await gateway.collect(ContractSymbol.BTCUSDT, as_of=NOW)

    assert error.value.code == "market_data_invalid_response"


@pytest.mark.asyncio
async def test_collect_rejects_an_oversized_payload_or_unexpected_response_host() -> None:
    client, gateway = _gateway(lambda _: httpx.Response(200, content=b"x" * 1_000_001))
    async with client:
        with pytest.raises(MarketDataUnavailableError):
            await gateway.collect(ContractSymbol.BTCUSDT, as_of=NOW)

    with pytest.raises(MarketDataUnavailableError):
        _gateway(lambda _: httpx.Response(200, text="unused"), base_url="https://example.com")


@pytest.mark.asyncio
async def test_gateway_rejects_a_nondefault_farside_port() -> None:
    async with httpx.AsyncClient(
        base_url="https://farside.co.uk:444",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="unused")),
    ) as client:
        with pytest.raises(MarketDataUnavailableError):
            FarsideEtfFlowGateway(client=client, clock=lambda: NOW)


@pytest.mark.asyncio
async def test_collect_never_follows_redirects_outside_the_fixed_origin() -> None:
    requests: list[httpx.Request] = []
    html = _actual_shape_page(_row("04 Sep 2026", tuple("0.0" for _ in range(12)), "0.0"))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "farside.co.uk":
            return httpx.Response(302, headers={"Location": "https://example.com/btc/"})
        return httpx.Response(200, text=html)

    client, gateway = _gateway(handler, follow_redirects=True)
    async with client:
        with pytest.raises(MarketDataUnavailableError) as error:
            await gateway.collect(ContractSymbol.BTCUSDT, as_of=NOW)

    assert error.value.code == "market_data_upstream_rejected"
    assert [request.url.host for request in requests] == ["farside.co.uk"]


@pytest.mark.asyncio
async def test_collect_rejects_a_historical_as_of_instead_of_backfilling_revisions() -> None:
    client, gateway = _gateway(lambda _: httpx.Response(200, text="unused"))
    async with client:
        with pytest.raises(MarketDataUnavailableError) as error:
            await gateway.collect(
                ContractSymbol.BTCUSDT,
                as_of=datetime(2026, 9, 5, 8, 0, tzinfo=UTC),
            )

    assert error.value.code == "market_data_historical_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("offset", "code"),
    [(-3600, "market_data_historical_unavailable"), (1, "market_data_invalid_request")],
)
async def test_collect_rejects_non_live_same_day_timestamps(offset: int, code: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="unused")

    client, gateway = _gateway(handler)
    async with client:
        with pytest.raises(MarketDataUnavailableError) as error:
            await gateway.collect(ContractSymbol.BTCUSDT, as_of=NOW + timedelta(seconds=offset))
    assert error.value.code == code
    assert requests == []


@pytest.mark.asyncio
async def test_collect_records_completion_time_with_a_small_live_collection_delay() -> None:
    html = _actual_shape_page(_row("04 Sep 2026", tuple("0.0" for _ in range(12)), "0.0"))
    times = iter((NOW, NOW + timedelta(seconds=2)))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html)),
    ) as client:
        gateway = FarsideEtfFlowGateway(client=client, clock=lambda: next(times))
        snapshot = await gateway.collect(ContractSymbol.BTCUSDT, as_of=NOW - timedelta(seconds=30))
    assert snapshot.fetched_at == NOW + timedelta(seconds=2)


@pytest.mark.asyncio
async def test_collect_maps_upstream_failures_and_propagates_cancellation() -> None:
    client, gateway = _gateway(lambda _: httpx.Response(503))
    async with client:
        with pytest.raises(MarketDataUnavailableError) as error:
            await gateway.collect(ContractSymbol.BTCUSDT, as_of=NOW)
    assert error.value.code == "market_data_unavailable"

    def cancelled(_: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    client, gateway = _gateway(cancelled)
    async with client:
        with pytest.raises(asyncio.CancelledError):
            await gateway.collect(ContractSymbol.BTCUSDT, as_of=NOW)
