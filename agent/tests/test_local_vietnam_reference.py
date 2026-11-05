"""Local HOSE references and declared price basis survive the real loader path."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backtest import runner
from backtest.engines.composite import CompositeEngine
from backtest.engines.vietnam_equity import VietnamEquityEngine
from backtest.loaders import base, local_loader
from backtest.loaders.registry import frame_caliber


def _source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides) -> dict:
    path = tmp_path / "hose.csv"
    path.write_text(
        "date,open,high,low,close,volume,Reference\n"
        "2025-01-02,27000,27100,26900,27000,1000000,27000\n"
        "2025-01-03,25900,26000,25800,25900,1000000,24250\n",
        encoding="utf-8",
    )
    entry = {
        "symbol": "VIC.VN", "type": "csv", "path": str(path),
        "columns": {"pre_close": "Reference"}, **overrides,
    }
    monkeypatch.setattr(local_loader, "_load_config", lambda: {"sources": [entry]})
    monkeypatch.setattr(base, "loader_cache_enabled", lambda: False)
    return entry


@pytest.mark.parametrize("source,code", [("local", "VIC.VN"), ("auto", "local:VIC.VN")])
@pytest.mark.parametrize("reference_column", ["Reference", "pre_close"])
def test_reference_reaches_hose_rule_through_fetch_data_map(
    tmp_path, monkeypatch, source, code, reference_column
):
    entry = _source(tmp_path, monkeypatch, adjustment="raw")
    if reference_column == "pre_close":
        path = Path(entry["path"])
        path.write_text(path.read_text().replace("Reference", "pre_close"))
        entry.pop("columns")

    def local_only(source_name):
        assert source_name == "local", "local data must not reach a network loader"
        return local_loader.DataLoader

    monkeypatch.setattr(runner, "_get_loader", local_only)
    monkeypatch.setattr(runner, "resolve_loader", lambda *_: pytest.fail("unexpected network routing"))
    result = runner.fetch_data_map({
        "source": source, "codes": [code],
        "start_date": "2025-01-02", "end_date": "2025-01-03",
    })
    frame = result.data_map["VIC.VN"]
    assert result.effective_sources == ["local"]
    assert frame["pre_close"].tolist() == [27000, 24250]
    assert frame.attrs["adjustment"] == "raw"

    engine = VietnamEquityEngine({"slippage": 0})
    engine._code_to_col = {"VIC.VN": 0}
    engine._close_arr = frame[["close"]].to_numpy()
    engine._bar_idx = 1
    # Previous close 27,000 would allow this buy; supplied reference 24,250
    # makes 25,900 the ceiling even though the previous bar closed elsewhere.
    assert engine._base_price("VIC.VN", frame.iloc[1]) == 24250
    assert engine.can_execute("VIC.VN", 1, frame.iloc[1]) is False
    assert "_run_card_caliber_warning" not in engine.config


def test_downsampling_keeps_opening_reference_and_missingness(tmp_path, monkeypatch):
    entry = _source(tmp_path, monkeypatch, adjustment="raw")
    pd.DataFrame({
        "date": ["2025-01-02 09:00", "2025-01-02 10:00", "2025-01-02 11:00",
                 "2025-01-06 09:00", "2025-01-06 10:00"],
        "open": [24500] * 5, "high": [24600] * 5,
        "low": [24400] * 5, "close": [24500] * 5,
        "volume": [100] * 5, "Reference": [None, 24250, 24250, 24000, 24100],
    }).to_csv(entry["path"], index=False)
    frame = local_loader.DataLoader().fetch(["VIC.VN"], "2025-01-02", "2025-01-06")["VIC.VN"]
    assert len(frame) == 2
    assert pd.isna(frame["pre_close"].iloc[0])
    assert frame["pre_close"].iloc[1] == 24000
    assert frame.attrs["adjustment"] == "raw"


@pytest.mark.parametrize("value", [None, "bad", -1, 0, float("inf")])
def test_invalid_reference_is_missing_and_warned_without_fabricating_a_price(value):
    frame = local_loader._normalize_columns(pd.DataFrame({
        "date": ["2025-01-02"], "open": [24500], "high": [24600],
        "low": [24400], "close": [24500], "pre_close": [value],
    }), dict(local_loader._DEFAULT_COLUMNS), None)
    assert pd.isna(frame["pre_close"].iloc[0])
    frame.attrs["adjustment"] = "raw"
    engine = VietnamEquityEngine({"_run_card_caliber_warning": "previous source warning"})
    assert engine._base_price("VIC.VN", frame.iloc[0]) is None
    assert engine.can_execute("VIC.VN", 1, frame.iloc[0]) is True
    assert engine.can_execute("VIC.VN", 1, frame.iloc[0]) is True
    warning = engine.config["_run_card_caliber_warning"]
    assert warning.startswith("previous source warning\n")
    assert warning.count("no reference price available") == 1


@pytest.mark.parametrize("declaration", [None, "raw", "split_dividend"])
def test_price_basis_and_reference_survive_the_real_cache(tmp_path, monkeypatch, declaration):
    entry = _source(tmp_path, monkeypatch)
    if declaration is not None:
        entry["adjustment"] = declaration
    monkeypatch.setattr(base, "loader_cache_enabled", lambda: True)
    monkeypatch.setattr(base, "loader_cache_root", lambda: tmp_path / "cache")
    first = local_loader.DataLoader().fetch(["VIC.VN"], "2025-01-02", "2025-01-03")["VIC.VN"]
    assert list((tmp_path / "cache").rglob("*.parquet")), "exercise persisted caching"

    def no_read(*_):
        raise AssertionError("an unchanged local source must hit its cache")

    monkeypatch.setitem(local_loader._READERS, "csv", no_read)
    second = local_loader.DataLoader().fetch(["VIC.VN"], "2025-01-02", "2025-01-03")["VIC.VN"]
    pd.testing.assert_frame_equal(first, second)
    assert second.attrs.get("adjustment", "unknown") == (declaration or "unknown")
    assert second["pre_close"].tolist() == [27000, 24250]


def test_changed_price_basis_is_not_hidden_by_cached_metadata(tmp_path, monkeypatch):
    entry = _source(tmp_path, monkeypatch)
    monkeypatch.setattr(base, "loader_cache_enabled", lambda: True)
    monkeypatch.setattr(base, "loader_cache_root", lambda: tmp_path / "cache")
    first = local_loader.DataLoader().fetch(["VIC.VN"], "2025-01-02", "2025-01-03")["VIC.VN"]
    entry["adjustment"] = "raw"
    second = local_loader.DataLoader().fetch(["VIC.VN"], "2025-01-02", "2025-01-03")["VIC.VN"]
    assert first.attrs.get("adjustment", "unknown") == "unknown"
    assert second.attrs["adjustment"] == "raw"


def test_omitted_declaration_keeps_existing_market_caliber_defaults(tmp_path, monkeypatch):
    _source(tmp_path, monkeypatch)
    frame = local_loader.DataLoader().fetch(["VIC.VN"], "2025-01-02", "2025-01-03")["VIC.VN"]
    assert frame_caliber(frame, "local", "vietnam_equity") == "unknown"
    assert frame_caliber(frame, "local", "index") == "raw"
    assert frame_caliber(frame, "local", "forex") == "na"


def test_invalid_price_basis_is_rejected(tmp_path, monkeypatch, caplog):
    _source(tmp_path, monkeypatch, adjustment="guessed_raw")
    assert local_loader.DataLoader().fetch(["VIC.VN"], "2025-01-02", "2025-01-03") == {}
    assert "invalid price adjustment declaration" in caplog.text


def test_composite_records_missing_reference_in_shared_run_config():
    config = {"codes": ["VIC.VN", "FPT.VN"], "_run_card_caliber_warning": "source note"}
    engine = CompositeEngine(config, config["codes"])
    bar = pd.Series({"open": 24500.0})
    assert engine.can_execute("VIC.VN", 1, bar) is True
    assert engine.can_execute("FPT.VN", 1, bar) is True
    warning = config["_run_card_caliber_warning"]
    assert warning.startswith("source note\n")
    assert "raw cash prices are not declared" in warning
    assert "no reference price available" in warning


@pytest.mark.parametrize("declaration,reference,filled,warned", [
    (None, 27000, True, True),
    ("raw", 27000, True, False),
    ("raw", 24250, False, False),
])
def test_full_backtest_uses_reference_and_records_price_basis(
    tmp_path, monkeypatch, declaration, reference, filled, warned
):
    entry = _source(tmp_path, monkeypatch)
    if declaration is not None:
        entry["adjustment"] = declaration
    config = {
        "source": "local", "codes": ["VIC.VN"], "initial_cash": 1000000000,
        "start_date": "2025-01-02", "end_date": "2025-01-03", "slippage": 0,
        "_run_card_caliber_warning": "original source warning",
    }
    path = Path(entry["path"])
    path.write_text(path.read_text().replace("24250", str(reference)))
    monkeypatch.setattr("backtest.benchmark.resolve_benchmark", lambda *args, **kwargs: None)

    class Signal:
        def generate(self, frames):
            return {"VIC.VN": pd.Series(0.5, index=frames["VIC.VN"].index)}

    engine = VietnamEquityEngine(config)
    engine.run_backtest(config, local_loader.DataLoader(), Signal(), tmp_path / "run")
    assert bool(engine.fill_records) is filled
    card = json.loads((tmp_path / "run" / "run_card.json").read_text(encoding="utf-8"))
    assert card["warnings"].count("original source warning") == 1
    assert any("raw cash prices are not declared" in warning for warning in card["warnings"]) is warned
