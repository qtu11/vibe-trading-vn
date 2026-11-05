"""Historical Binance USD-M data-contract tests."""

from __future__ import annotations

import hashlib
import json

import pytest
import pandas as pd

from backtest.loaders.base import make_loader_cache_key
from backtest.loaders.ccxt_loader import _parse_ccxt_symbol, _validate_bracket_artifact
from tests.loader_contract import assert_loader_contract


def _hourly_rows(opens: list[float]) -> list[list[float]]:
    start = int(pd.Timestamp("2024-01-01 00:00:00").timestamp() * 1000)
    hour = 3_600_000
    return [
        [start + i * hour, value, value + 2, value - 2, value + 1, 10 + i]
        for i, value in enumerate(opens)
    ]


class _PerpetualExchange:
    """Fake exchange with no ``fetch_leverage_tiers`` — proves the loader
    never calls the authenticated bracket endpoint. If any code path tried
    to, this fake would raise ``AttributeError`` instead of silently
    succeeding.
    """

    def __init__(
        self,
        *,
        mark_rows: list[list[float]] | None = None,
        funding_rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.trade_rows = _hourly_rows([100.0, 101.0])
        self.mark_rows = mark_rows if mark_rows is not None else _hourly_rows([99.0, 100.0])
        start = int(pd.Timestamp("2024-01-01 00:00:00").timestamp() * 1000)
        self.funding_rows = (
            funding_rows
            if funding_rows is not None
            else [{"timestamp": start, "fundingRate": 0.0}]
        )
        self.calls: list[dict[str, object]] = []

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None, params=None):
        self.calls.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "since": since,
            "limit": limit,
            "params": params,
        })
        return self.mark_rows if params == {"price": "mark"} else self.trade_rows

    def fetch_funding_rate_history(self, symbol, since=None, limit=None):
        self.calls.append({
            "funding_symbol": symbol,
            "since": since,
            "limit": limit,
        })
        return self.funding_rows


_DEFAULT_BRACKET_RECORDS = [
    {
        "bracket_tier": 1,
        "notional_cap": 50_000.0,
        "maintenance_rate": 0.004,
        "cumulative_maintenance_amount": 0.0,
    },
    {
        "bracket_tier": 2,
        "notional_cap": 250_000.0,
        "maintenance_rate": 0.005,
        "cumulative_maintenance_amount": 50.0,
    },
]


def _bracket_content_hash(records: list[dict]) -> str:
    """Mirror ``_validate_bracket_artifact``'s canonical hashing exactly."""
    blob = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _make_bracket_artifact(
    *, symbol: str = "BTC/USDT:USDT", brackets: list[dict] | None = None, **overrides,
) -> dict:
    records = _DEFAULT_BRACKET_RECORDS if brackets is None else brackets
    artifact = {
        "schema_version": 1,
        "symbol": symbol,
        "provenance_timestamp": "2024-01-01T00:00:00Z",
        "brackets": records,
        "content_hash": _bracket_content_hash(records),
    }
    artifact.update(overrides)
    return artifact


def test_spot_symbol_keeps_existing_ccxt_contract() -> None:
    assert _parse_ccxt_symbol("BTC-USDT") == ("BTC/USDT", "spot")


def test_perpetual_symbol_maps_to_binance_usdm_contract() -> None:
    assert _parse_ccxt_symbol("BTC-USDT-PERP") == ("BTC/USDT:USDT", "swap")


@pytest.mark.parametrize("code", ["BTC-PERP", "-USDT-PERP", "BTC--PERP"])
def test_malformed_perpetual_symbol_is_rejected(code: str) -> None:
    with pytest.raises(ValueError, match="USD-M perpetual symbol"):
        _parse_ccxt_symbol(code)


def test_spot_and_perpetual_cache_keys_cannot_collide() -> None:
    common = {
        "source": "ccxt",
        "timeframe": "1H",
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "fields": None,
    }
    spot = make_loader_cache_key(symbol="BTC-USDT", **common)
    perpetual = make_loader_cache_key(symbol="BTC-USDT-PERP", **common)
    assert spot != perpetual


def test_perpetual_fetch_separates_execution_and_mark_prices(monkeypatch) -> None:
    exchange = _PerpetualExchange()
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    frame = DataLoader().fetch(
        ["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1H"
    )["BTC-USDT-PERP"]

    assert frame["execution_open"].tolist() == [100.0, 101.0]
    assert frame["mark_open"].tolist() == [99.0, 100.0]
    assert frame["mark_high"].tolist() == [101.0, 102.0]
    assert frame["mark_low"].tolist() == [97.0, 98.0]
    assert frame["mark_close"].tolist() == [100.0, 101.0]
    assert exchange.calls[0]["symbol"] == "BTC/USDT:USDT"
    assert exchange.calls[0]["params"] is None
    assert exchange.calls[1]["params"] == {"price": "mark"}


def test_perpetual_fetch_rejects_unsynchronized_mark_rows(monkeypatch) -> None:
    mark_rows = _hourly_rows([99.0, 100.0])
    mark_rows[1][0] += 60_000
    exchange = _PerpetualExchange(mark_rows=mark_rows)
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    with pytest.raises(ValueError, match="mark-price timestamps"):
        DataLoader().fetch(
            ["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1H"
        )


def test_perpetual_fetch_aligns_explicit_zero_funding_settlement(monkeypatch) -> None:
    exchange = _PerpetualExchange()
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    frame = DataLoader().fetch(
        ["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1H"
    )["BTC-USDT-PERP"]

    assert frame["funding_rate"].tolist() == [0.0, 0.0]
    assert frame["funding_settlement_time"].iloc[0] == pd.Timestamp("2024-01-01")
    assert pd.isna(frame["funding_settlement_time"].iloc[1])


def test_perpetual_fetch_rejects_missing_required_funding_settlement(monkeypatch) -> None:
    exchange = _PerpetualExchange(funding_rows=[])
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    with pytest.raises(ValueError, match="funding settlement"):
        DataLoader().fetch(
            ["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1H"
        )


def test_perpetual_fetch_rejects_duplicate_funding_settlement(monkeypatch) -> None:
    start = int(pd.Timestamp("2024-01-01 00:00:00").timestamp() * 1000)
    exchange = _PerpetualExchange(funding_rows=[
        {"timestamp": start, "fundingRate": 0.0001},
        {"timestamp": start, "fundingRate": 0.0002},
    ])
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    with pytest.raises(ValueError, match="duplicate funding settlement"):
        DataLoader().fetch(
            ["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1H"
        )


def test_perpetual_fetch_has_no_bracket_columns_without_artifact(monkeypatch) -> None:
    """Normal perpetual fetch stays zero-credential: no artifact in, no
    bracket columns out, and no bracket-endpoint call ever attempted (the
    fake exchange has no ``fetch_leverage_tiers`` at all)."""
    exchange = _PerpetualExchange()
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    frame = DataLoader().fetch(
        ["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1H"
    )["BTC-USDT-PERP"]

    assert_loader_contract(frame, context="ccxt perpetual 1H")
    assert "maintenance_brackets" not in frame.columns
    assert "maintenance_bracket_version" not in frame.columns
    assert all("bracket" not in str(call) for call in exchange.calls)


def test_perpetual_fetch_attaches_valid_bracket_artifact(monkeypatch) -> None:
    exchange = _PerpetualExchange()
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    artifact = _make_bracket_artifact()
    frame = DataLoader().fetch(
        ["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1H",
        bracket_artifacts={"BTC-USDT-PERP": artifact},
    )["BTC-USDT-PERP"]

    versions = frame["maintenance_bracket_version"].unique().tolist()
    assert versions == [artifact["content_hash"]]
    assert json.loads(frame["maintenance_brackets"].iloc[0]) == _DEFAULT_BRACKET_RECORDS
    assert frame["maintenance_brackets"].nunique() == 1


def test_strict_perpetual_fetch_without_artifact_fails_closed_before_any_call(monkeypatch) -> None:
    exchange = _PerpetualExchange()
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    with pytest.raises(ValueError, match="requires a maintenance-bracket artifact"):
        DataLoader().fetch(
            ["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1H",
            require_brackets=True,
        )
    assert exchange.calls == []


def test_strict_perpetual_fetch_with_valid_artifact_succeeds(monkeypatch) -> None:
    exchange = _PerpetualExchange()
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    artifact = _make_bracket_artifact()
    frame = DataLoader().fetch(
        ["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1H",
        bracket_artifacts={"BTC-USDT-PERP": artifact}, require_brackets=True,
    )["BTC-USDT-PERP"]

    assert frame["maintenance_bracket_version"].iloc[0] == artifact["content_hash"]


def test_bracket_artifact_accepts_optional_notional_coefficient() -> None:
    records = [
        {**_DEFAULT_BRACKET_RECORDS[0], "notional_coefficient": 1.5},
        _DEFAULT_BRACKET_RECORDS[1],
    ]
    artifact = _make_bracket_artifact(brackets=records)
    brackets, version = _validate_bracket_artifact(artifact, expected_symbol="BTC/USDT:USDT")
    assert brackets[0]["notional_coefficient"] == 1.5
    assert "notional_coefficient" not in brackets[1]
    assert version == artifact["content_hash"]


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"schema_version": 2}, "schema_version"),
        ({"symbol": "ETH/USDT:USDT"}, "symbol mismatch"),
        ({"provenance_timestamp": ""}, "provenance_timestamp"),
        ({"provenance_timestamp": "not-a-timestamp"}, "provenance_timestamp"),
        ({"brackets": []}, "no brackets"),
        ({"content_hash": "deadbeefdeadbeef"}, "content_hash mismatch"),
    ],
)
def test_bracket_artifact_rejects_invalid_fields(overrides: dict, match: str) -> None:
    artifact = _make_bracket_artifact(**overrides)
    with pytest.raises(ValueError, match=match):
        _validate_bracket_artifact(artifact, expected_symbol="BTC/USDT:USDT")


def test_bracket_artifact_rejects_tier_missing_required_field() -> None:
    artifact = _make_bracket_artifact(brackets=[
        {"bracket_tier": 1, "notional_cap": 50_000.0, "maintenance_rate": 0.004},
    ])
    with pytest.raises(ValueError, match="missing a required field"):
        _validate_bracket_artifact(artifact, expected_symbol="BTC/USDT:USDT")


def test_bracket_artifact_rejects_non_numeric_notional_coefficient() -> None:
    records = [{**_DEFAULT_BRACKET_RECORDS[0], "notional_coefficient": "not-a-number"}]
    artifact = _make_bracket_artifact(brackets=records)
    with pytest.raises(ValueError, match="notional_coefficient must be numeric"):
        _validate_bracket_artifact(artifact, expected_symbol="BTC/USDT:USDT")


def test_bracket_artifact_rejects_non_monotonic_brackets() -> None:
    artifact = _make_bracket_artifact(brackets=[
        {
            "bracket_tier": 1, "notional_cap": 250_000.0,
            "maintenance_rate": 0.004, "cumulative_maintenance_amount": 0.0,
        },
        {
            "bracket_tier": 2, "notional_cap": 50_000.0,
            "maintenance_rate": 0.005, "cumulative_maintenance_amount": 50.0,
        },
    ])
    with pytest.raises(ValueError, match="not strictly increasing"):
        _validate_bracket_artifact(artifact, expected_symbol="BTC/USDT:USDT")


def test_perpetual_fetch_rounds_funding_settlement_jitter(monkeypatch) -> None:
    """Binance returns settlement timestamps with millisecond jitter
    (e.g. ``08:00:00.011``); the loader must round them to the second so
    they align with bar timestamps instead of raising the
    missing-settlement error."""
    start = int(pd.Timestamp("2024-01-01 00:00:00").timestamp() * 1000)
    exchange = _PerpetualExchange(
        funding_rows=[{"timestamp": start + 11, "fundingRate": 0.0003}]
    )
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    frame = DataLoader().fetch(
        ["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1H"
    )["BTC-USDT-PERP"]

    assert frame["funding_rate"].tolist() == [0.0003, 0.0]
    assert frame["funding_settlement_time"].iloc[0] == pd.Timestamp("2024-01-01")


def test_daily_perpetual_fetch_rejects_c06_intrabar_funding_loss(monkeypatch) -> None:
    """C06: a daily row must not silently retain only the midnight payment."""
    start = int(pd.Timestamp("2024-01-01").timestamp() * 1000)
    settlements = [(0, 0.0001, 50_000), (8, -0.0002, 51_000), (16, 0.0003, 49_000)]
    exchange = _PerpetualExchange(funding_rows=[
        {"timestamp": start + hour * 3_600_000, "fundingRate": rate}
        for hour, rate, _mark in settlements
    ])
    exchange.trade_rows = _hourly_rows([50_000.0])
    exchange.mark_rows = _hourly_rows([50_000.0])
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    # Independent long-0.1-BTC cash oracle: -0.50 + 1.02 - 1.47 = -0.95 USDT.
    assert -sum(0.1 * mark * rate for _hour, rate, mark in settlements) == pytest.approx(-0.95)

    from backtest.loaders.ccxt_loader import DataLoader

    with pytest.raises(ValueError, match="funding settlements cannot be represented on 1d") as error:
        DataLoader().fetch(["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1D")
    assert "2024-01-01 08:00:00" in str(error.value)
    assert "2024-01-01 16:00:00" in str(error.value)
    assert "finer aligned interval" in str(error.value)


@pytest.mark.parametrize("interval", ["1H", "4H"])
def test_perpetual_fetch_preserves_c06_funding_cashflows_on_aligned_grid(monkeypatch, interval) -> None:
    start = int(pd.Timestamp("2024-01-01").timestamp() * 1000)
    exchange = _PerpetualExchange(funding_rows=[
        {"timestamp": start + hour * 3_600_000, "fundingRate": rate}
        for hour, rate in [(0, 0.0001), (8, -0.0002), (16, 0.0003)]
    ])
    exchange.trade_rows = _hourly_rows([50_000.0] * 24)
    exchange.mark_rows = _hourly_rows([50_000.0] * 8 + [51_000.0] * 8 + [49_000.0] * 8)
    if interval == "4H":
        exchange.trade_rows = exchange.trade_rows[::4]
        exchange.mark_rows = exchange.mark_rows[::4]
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    frame = DataLoader().fetch(
        ["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval=interval
    )["BTC-USDT-PERP"]

    events = frame[frame["funding_settlement_time"].notna()]
    assert events.index.hour.tolist() == [0, 8, 16]
    assert events["funding_rate"].tolist() == [0.0001, -0.0002, 0.0003]
    assert -(0.1 * events["mark_open"] * events["funding_rate"]).sum() == pytest.approx(-0.95)


def test_hourly_perpetual_fetch_preserves_observed_four_hour_funding(monkeypatch) -> None:
    start = int(pd.Timestamp("2024-01-01").timestamp() * 1000)
    exchange = _PerpetualExchange(funding_rows=[
        {"timestamp": start + hour * 3_600_000, "fundingRate": 0.0001}
        for hour in range(0, 24, 4)
    ])
    exchange.trade_rows = _hourly_rows([100.0] * 24)
    exchange.mark_rows = _hourly_rows([100.0] * 24)
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    frame = DataLoader().fetch(
        ["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1H"
    )["BTC-USDT-PERP"]

    events = frame[frame["funding_settlement_time"].notna()]
    assert events.index.hour.tolist() == [0, 4, 8, 12, 16, 20]
    assert -(0.1 * events["mark_open"] * events["funding_rate"]).sum() == pytest.approx(-0.006)


@pytest.mark.parametrize("rate", [0.0, 0.0001])
def test_perpetual_fetch_rejects_four_hour_grid_with_two_hour_settlement(monkeypatch, rate) -> None:
    start = int(pd.Timestamp("2024-01-01").timestamp() * 1000)
    exchange = _PerpetualExchange(funding_rows=[
        {"timestamp": start, "fundingRate": 0.0001},
        {"timestamp": start + 2 * 3_600_000, "fundingRate": rate},
    ])
    exchange.trade_rows = _hourly_rows([100.0] * 5)[::4]
    exchange.mark_rows = _hourly_rows([100.0] * 5)[::4]
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    with pytest.raises(ValueError, match="funding settlements cannot be represented on 4h"):
        DataLoader().fetch(["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="4H")


def test_minute_perpetual_fetch_requires_funding_only_at_settlement_boundary(monkeypatch) -> None:
    exchange = _PerpetualExchange()
    exchange.trade_rows[1][0] = exchange.trade_rows[0][0] + 60_000
    exchange.mark_rows[1][0] = exchange.mark_rows[0][0] + 60_000
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    from backtest.loaders.ccxt_loader import DataLoader

    frame = DataLoader().fetch(
        ["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1m"
    )["BTC-USDT-PERP"]

    assert frame.index.tolist() == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-01 00:01")]
    assert frame["funding_settlement_time"].notna().tolist() == [True, False]


def test_legacy_perpetual_cache_cannot_bypass_funding_grid_validation(monkeypatch, tmp_path) -> None:
    from backtest.loaders import base
    from backtest.loaders.ccxt_loader import DataLoader

    monkeypatch.setattr(base, "loader_cache_enabled", lambda: True)
    monkeypatch.setattr(base, "loader_cache_root", lambda: tmp_path / "cache")
    legacy = pd.DataFrame(
        {
            "open": [50_000.0], "high": [50_001.0], "low": [49_999.0],
            "close": [50_000.0], "volume": [1.0], "funding_rate": [0.0001],
            "funding_settlement_time": [pd.Timestamp("2024-01-01")],
        },
        index=pd.DatetimeIndex(["2024-01-01"], name="trade_date"),
    )
    payload = {
        "source": "ccxt", "symbol": "BTC-USDT-PERP", "timeframe": "1D",
        "start_date": "2024-01-01", "end_date": "2024-01-01", "fields": None,
    }
    base.loader_cache_put(**payload, frame=legacy)
    assert base.loader_cache_get(**payload) is not None

    start = int(pd.Timestamp("2024-01-01").timestamp() * 1000)
    exchange = _PerpetualExchange(funding_rows=[
        {"timestamp": start + hour * 3_600_000, "fundingRate": 0.0001}
        for hour in (0, 8, 16)
    ])
    exchange.trade_rows = _hourly_rows([50_000.0])
    exchange.mark_rows = _hourly_rows([50_000.0])
    monkeypatch.setattr(
        "backtest.loaders.ccxt_loader.DataLoader._get_exchange",
        lambda _self, instrument_type="spot": exchange,
    )

    with pytest.raises(ValueError, match="funding settlements cannot be represented on 1d"):
        DataLoader().fetch(["BTC-USDT-PERP"], "2024-01-01", "2024-01-01", interval="1D")
    assert any("funding_symbol" in call for call in exchange.calls)
