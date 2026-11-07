"""Vietnam technical figures from the real tool contract, with no market I/O.

The test calls the production indicator calculator over a deterministic supplied
OHLCV frame. It then checks the final answer gate, not a hand-built alias map.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.evidence import _is_registered_price_indicator
from src.tools import technical_indicator_tool as indicator_module
from src.tools.technical_indicator_tool import TechnicalIndicatorTool

pytestmark = pytest.mark.unit
SYMBOL = "FPT.VN"
CALL = "indicators-fpt"


@pytest.fixture
def indicator_payload(monkeypatch):
    from src.trading.forex import research

    closes = [81500.0 + i * 125 + ((i % 7) - 3) * 90 for i in range(64)]
    frame = pd.DataFrame(
        {
            "open": [value - 80 for value in closes],
            "high": [value + 150 for value in closes],
            "low": [value - 180 for value in closes],
            "close": closes,
            "volume": [1000000.0 + (i % 9) * 75000 for i in range(63)] + [2567000.0],
        },
        index=pd.date_range("2026-07-01", periods=64, freq="B"),
    )
    provenance = {"source": "vnstock", "currency": "VND", "volume_unit": "shares"}
    monkeypatch.setattr(research, "native_market_data", lambda *a, **kw: None)
    monkeypatch.setattr(
        indicator_module, "fetch_market_data",
        lambda **kwargs: {SYMBOL: frame, "_provenance": {SYMBOL: provenance}},
    )
    raw = TechnicalIndicatorTool().execute(symbol=SYMBOL, interval="1d", lookback=64, end_date="2026-10-01")
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["indicators"]["volume"]["unit"] == "shares"
    assert payload["read_identity"]["dataset_fingerprint"]
    return payload


def _ledger(tmp_path: Path, payload: dict) -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Phân tích cổ phiếu FPT.VN, Bollinger và khối lượng.")
    ledger.ingest_tool_result(
        tool_name="technical_indicators", arguments={"symbol": SYMBOL},
        result=json.dumps(payload), call_id=CALL, success=True,
    )
    return ledger


def _answer(value: str, field: str, *, symbol=SYMBOL, unit="", label="Giá trị đã tính"):
    prose = f"{symbol} (vnstock, VND): {label} {value}{(' ' + unit) if unit else ''}."
    declaration = f"\n\n```figures\n{value}{(' ' + unit) if unit else ''} | observed | {label} | {CALL}::{field}\n```"
    return prose, prose + declaration


@pytest.mark.parametrize("band", ["upper", "middle", "lower"])
def test_actual_bollinger_bands_release_unchanged_with_exact_refs(tmp_path, indicator_payload, band):
    value = str(indicator_payload["indicators"]["bollinger"][band])
    prose, answer = _answer(value, f"indicators.bollinger.{band}", unit="VND", label=f"Bollinger {band}")
    result = _ledger(tmp_path, indicator_payload).validate_final_answer(answer)
    assert result.valid, result.issues
    assert result.released_text.strip() == prose
    assert value in result.released_text


def test_actual_volume_ratio_releases_unchanged_with_exact_ref(tmp_path, indicator_payload):
    value = str(indicator_payload["indicators"]["volume"]["ratio_20"])
    prose, answer = _answer(value, "indicators.volume.ratio_20", label="Tỷ lệ khối lượng so với trung bình")
    result = _ledger(tmp_path, indicator_payload).validate_final_answer(answer)
    assert result.valid, result.issues
    assert result.released_text.strip() == prose
    assert value in result.released_text


@pytest.mark.parametrize("field", ["indicators.bollinger.upper", "indicators.volume.ratio_20"])
def test_indicator_exact_ref_cannot_be_relabelled_as_another_symbol(tmp_path, indicator_payload, field):
    value = indicator_payload["indicators"]["bollinger"]["upper"] if "bollinger" in field else indicator_payload["indicators"]["volume"]["ratio_20"]
    _, answer = _answer(str(value), field, symbol="VNM.VN")
    result = _ledger(tmp_path, indicator_payload).validate_final_answer(answer)
    assert not result.valid
    assert any(issue["code"] in {"numeric_claim_conflict", "unsourced_symbol_figures", "figure_symbol_mismatch"} for issue in result.issues)


@pytest.mark.parametrize("field,value", [("indicators.bollinger.upper", "123456.78"), ("indicators.volume.ratio_20", "7.654321")])
def test_indicator_exact_ref_rejects_wrong_value(tmp_path, indicator_payload, field, value):
    _, answer = _answer(value, field)
    result = _ledger(tmp_path, indicator_payload).validate_final_answer(answer)
    assert not result.valid
    assert any(issue["code"] == "numeric_claim_conflict" for issue in result.issues)


@pytest.mark.parametrize("field,unit", [("indicators.bollinger.upper", "USD"), ("indicators.volume.ratio_20", "VND")])
def test_price_currency_and_dimensionless_volume_ratio_are_not_interchangeable(tmp_path, indicator_payload, field, unit):
    value = indicator_payload["indicators"]["bollinger"]["upper"] if "bollinger" in field else indicator_payload["indicators"]["volume"]["ratio_20"]
    _, answer = _answer(str(value), field, unit=unit)
    result = _ledger(tmp_path, indicator_payload).validate_final_answer(answer)
    assert not result.valid
    assert any(issue["code"] == "numeric_claim_conflict" for issue in result.issues)


def test_volume_statistic_aliases_do_not_become_price_levels():
    assert _is_registered_price_indicator("technical_indicators", "indicators.bollinger.upper")
    assert not _is_registered_price_indicator("technical_indicators", "indicators.volume.sma_20")
    assert not _is_registered_price_indicator("technical_indicators", "indicators.volume.ratio_20")
    assert not _is_registered_price_indicator("technical_indicators", "indicators.sma_cross")
    assert not _is_registered_price_indicator("custom_indicator_tool", "indicators.bollinger.upper")


@pytest.mark.parametrize("field", ["latest_close_count", "indicators.bollinger.upper_percent", "indicators.bollinger.lower.window"])
def test_fixed_price_indicator_leaves_do_not_authorize_lookalike_fields(field):
    assert not _is_registered_price_indicator("technical_indicators", field)


def test_volume_ratio_percentage_must_apply_the_hundredfold_conversion(tmp_path, indicator_payload):
    """A ratio of 1.9x is 190%, not 1.9%; exact refs do not change units."""
    value = str(indicator_payload["indicators"]["volume"]["ratio_20"])
    _, answer = _answer(value, "indicators.volume.ratio_20", unit="%")
    result = _ledger(tmp_path, indicator_payload).validate_final_answer(answer)
    assert not result.valid
    assert any(issue["code"] == "numeric_claim_conflict" for issue in result.issues)


def test_volume_ratio_can_be_expressed_as_the_correct_converted_percentage(tmp_path, indicator_payload):
    ratio = indicator_payload["indicators"]["volume"]["ratio_20"]
    value = f"{ratio * 100:.4f}"
    prose, answer = _answer(value, "indicators.volume.ratio_20", unit="%")
    result = _ledger(tmp_path, indicator_payload).validate_final_answer(answer)
    assert result.valid, result.issues
    assert result.released_text.strip() == prose


def test_price_bollinger_band_is_never_a_percentage(tmp_path, indicator_payload):
    value = str(indicator_payload["indicators"]["bollinger"]["upper"])
    _, answer = _answer(value, "indicators.bollinger.upper", unit="%")
    result = _ledger(tmp_path, indicator_payload).validate_final_answer(answer)
    assert not result.valid
    assert any(issue["code"] == "numeric_claim_conflict" for issue in result.issues)


def test_conflicting_result_symbol_cannot_supply_the_requested_company(tmp_path, indicator_payload):
    """The returned identity must agree with the request before values enter."""
    conflicting = dict(indicator_payload, symbol="VNM.VN")
    value = str(indicator_payload["indicators"]["bollinger"]["upper"])
    _, answer = _answer(value, "indicators.bollinger.upper", unit="VND")
    result = _ledger(tmp_path, conflicting).validate_final_answer(answer)
    assert not result.valid
