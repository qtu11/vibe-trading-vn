"""Offline mathematical, temporal and transport contracts for supplied basis."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.tools import crypto_basis as domain
from src.tools.crypto_basis import CryptoBasisRequest, build_crypto_basis
from src.tools.crypto_basis_tool import CryptoBasisTool

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "docs/examples/crypto-basis.example.json"


@pytest.fixture
def payload():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def one(payload):
    payload["futures"] = payload["futures"][:1]
    return payload


def result_row(payload):
    return build_crypto_basis(payload)["rows"][0]


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def test_master_plan_oracle_signed_curve_and_units(payload):
    result = build_crypto_basis(payload)
    assert result["summary"] == {"total": 3, "accepted": 2, "rejected": 1}
    assert result["verification_status"] == "user_supplied_unverified"
    assert result["price_unit"] == "USDT/CASE"
    assert result["spot"]["mid_price"] == "100"
    row = result["rows"][0]
    assert row["basis_fraction"] == "0.02"
    assert row["basis_quote_per_base"] == "2"
    assert row["seconds_to_expiry"] == "2592000"
    assert float(row["annualized_basis"]) == pytest.approx(0.02 * 365 / 30)
    assert Decimal(row["lower_basis_fraction"]) < Decimal(row["basis_fraction"]) < Decimal(row["upper_basis_fraction"])
    assert Decimal(result["rows"][1]["annualized_basis"]) < 0
    rejected = result["rows"][2]
    assert rejected["annualized_basis"] is None
    assert "perpetual_has_no_dated_basis" in rejected["reason_codes"]
    assert "expiry_missing" in rejected["reason_codes"]


def test_zero_basis_and_locked_quotes_are_valid(payload):
    one(payload)
    payload["spot"].update(bid="100", ask="100")
    payload["futures"][0].update(bid="100", ask="100")
    row = result_row(payload)
    assert row["status"] == "accepted"
    assert {row[key] for key in ("basis_fraction", "annualized_basis", "annualized_lower_basis", "annualized_upper_basis")} == {"0"}


def test_bid_ask_bounds_follow_gross_two_leg_quote_ratios(payload):
    row = result_row(payload)
    assert float(row["lower_basis_fraction"]) == pytest.approx(101.9 / 100.1 - 1)
    assert float(row["upper_basis_fraction"]) == pytest.approx(102.1 / 99.9 - 1)
    assert float(row["annualized_lower_basis"]) == pytest.approx((101.9 / 100.1 - 1) * 365 / 30)


def test_exact_intraday_fraction_across_utc_midnight_reuses_quantlib(payload, monkeypatch):
    one(payload)
    payload["as_of"] = "2026-11-06T23:30:00.500000Z"
    payload["spot"].update(event_time=payload["as_of"], available_at=payload["as_of"])
    payload["futures"][0].update(event_time=payload["as_of"], available_at=payload["as_of"], expiry="2026-11-07T00:00:00.500000Z")
    calls = []
    primitive = domain.year_fraction
    monkeypatch.setattr(domain, "year_fraction", lambda start, end, convention: (calls.append((start, end, convention)), primitive(start, end, convention))[1])
    row = result_row(payload)
    assert row["seconds_to_expiry"] == "1800"
    assert float(row["years_to_expiry"]) == pytest.approx(1800 / (365 * 86400))
    assert float(row["annualized_basis"]) == pytest.approx(0.02 * 365 * 48)
    assert calls[0][2] == "ACT/365F"


def test_subsecond_term_and_equivalent_offset_canonical_hash(payload):
    one(payload)
    payload["futures"][0]["expiry"] = "2026-11-06T08:00:00.000001Z"
    result = build_crypto_basis(payload)
    assert result["rows"][0]["seconds_to_expiry"] == "0.000001"
    shifted = deepcopy(payload)
    shifted["as_of"] = "2026-11-06T15:00:00+07:00"
    assert build_crypto_basis(shifted)["input_sha256"] == result["input_sha256"]
    assert Decimal(result["rows"][0]["annualized_basis"]).is_finite()


@pytest.mark.parametrize("field,value,reason", [
    ("kind", "perpetual", "perpetual_has_no_dated_basis"),
    ("expiry", None, "expiry_missing"),
    ("expiry", "2026-11-06T08:00:00Z", "expiry_not_after_cutoff"),
    ("expiry", "2026-11-05T08:00:00Z", "expiry_not_after_cutoff"),
    ("linear", False, "nonlinear_contract_unsupported"),
    ("base", "OTHER", "future_identity_mismatch"),
    ("quote", "USDC", "future_identity_mismatch"),
    ("settle", "USD", "future_identity_mismatch"),
    ("event_time", "2026-11-06T08:00:01Z", "future_event_after_cutoff"),
    ("available_at", "2026-11-06T08:00:01Z", "future_unavailable_at_cutoff"),
    ("available_at", "2026-11-06T07:59:58Z", "future_availability_before_event"),
    ("event_time", "2026-11-06T07:59:54Z", "future_stale"),
])
def test_semantic_rejection_never_annualizes(payload, field, value, reason):
    one(payload)["futures"][0][field] = value
    row = result_row(payload)
    assert row["status"] == "rejected"
    assert reason in row["reason_codes"]
    assert all(row[key] is None for key in ("mid_price", "basis_fraction", "annualized_basis", "annualized_lower_basis", "annualized_upper_basis", "years_to_expiry"))


@pytest.mark.parametrize("field,value,reason", [
    ("base", "OTHER", "spot_identity_mismatch"),
    ("event_time", "2026-11-06T08:00:01Z", "spot_event_after_cutoff"),
    ("available_at", "2026-11-06T08:00:01Z", "spot_unavailable_at_cutoff"),
    ("available_at", "2026-11-06T07:59:58Z", "spot_availability_before_event"),
    ("event_time", "2026-11-06T07:59:54Z", "spot_stale"),
])
def test_shared_spot_failure_rejects_every_row(payload, field, value, reason):
    payload["spot"][field] = value
    result = build_crypto_basis(payload)
    assert result["summary"]["accepted"] == 0
    assert all(reason in row["reason_codes"] and row["annualized_basis"] is None for row in result["rows"])


def test_age_and_skew_exact_equality_pass_and_one_microsecond_beyond_fails(payload):
    one(payload)
    payload["policy"].update(max_quote_age_seconds=5, max_pair_skew_seconds=4)
    payload["futures"][0]["event_time"] = "2026-11-06T07:59:55Z"
    assert result_row(payload)["status"] == "accepted"
    payload["futures"][0]["event_time"] = "2026-11-06T07:59:54.999999Z"
    row = result_row(payload)
    assert {"future_stale", "quote_pair_skew_exceeded"} <= set(row["reason_codes"])


def test_zero_policy_accepts_only_exact_common_cutoff(payload):
    one(payload)
    payload["policy"].update(max_quote_age_seconds=0, max_pair_skew_seconds=0)
    for quote in (payload["spot"], payload["futures"][0]):
        quote.update(event_time=payload["as_of"], available_at=payload["as_of"])
    assert result_row(payload)["status"] == "accepted"


@pytest.mark.parametrize("value", [0, 100, 100.1, True, None, "0", "-1", "NaN", "Infinity", "1e999", "1e-999", "01", "1e25", "0.0000000000001", "1 " ])
def test_malformed_prices_reject_entire_payload(payload, value):
    payload["futures"][0]["bid"] = value
    with pytest.raises((ValueError, ValidationError)):
        build_crypto_basis(payload)


@pytest.mark.parametrize("value", ["2026-11-06", "2026-11-06T08:00:00", "2026-11-06 08:00:00Z", "2026-13-06T08:00:00Z", "9999-11-06T08:00:00Z", "2026-11-06T08:00:00+25:00"])
def test_malformed_future_times_rejected_at_shape_validation(payload, value):
    payload["futures"][0]["event_time"] = value
    with pytest.raises(ValidationError):
        build_crypto_basis(payload)


@pytest.mark.parametrize("value", ["javascript:alert", "data:text", "file:private", "file:///tmp/file", "https://u:p@example.com/quote", "https://example.com:bad/x", "https://example.com/ bad", "", "x" * 241])
def test_source_refs_are_bounded_and_nonexecuting(payload, value):
    payload["spot"]["source_ref"] = value
    with pytest.raises(ValidationError):
        build_crypto_basis(payload)


def test_source_reference_url_is_declared_and_never_fetched(payload, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("No network allowed"))
    payload["spot"]["source_ref"] = "https://example.com/quotes/spot"
    result = build_crypto_basis(payload)
    assert "https://example.com/quotes/spot" in result["provenance"]["source_refs"]
    assert "no source was fetched or verified" in result["provenance"]["source_verification"]


@pytest.mark.parametrize("mutation", ["duplicate", "crossed", "extra", "empty", "thirteen", "bool_policy", "string_bool", "missing_expiry", "same_asset", "size", "nan"])
def test_whole_payload_shape_failures(payload, mutation):
    if mutation == "duplicate": payload["futures"].append(deepcopy(payload["futures"][0]))
    elif mutation == "crossed": payload["spot"].update(bid="101", ask="100")
    elif mutation == "extra": payload["result"] = {"annualized_basis": "100"}
    elif mutation == "empty": payload["futures"] = []
    elif mutation == "thirteen": payload["futures"] = [dict(payload["futures"][0], instrument_id=f"future-{i}") for i in range(13)]
    elif mutation == "bool_policy": payload["policy"]["max_quote_age_seconds"] = True
    elif mutation == "string_bool": payload["futures"][0]["linear"] = "true"
    elif mutation == "missing_expiry": del payload["futures"][0]["expiry"]
    elif mutation == "same_asset": payload["base"] = payload["quote"]
    elif mutation == "size": payload["unexpected"] = "a" * 64000
    elif mutation == "nan": payload["unexpected"] = float("nan")
    with pytest.raises((ValueError, ValidationError)):
        build_crypto_basis(payload)


def test_identity_conflict_is_not_hidden_by_kind_tag(payload):
    one(payload)
    payload["futures"][0].update(venue=payload["spot"]["venue"], instrument_id=payload["spot"]["instrument_id"])
    assert "spot_future_identity_conflict" in result_row(payload)["reason_codes"]


def test_utc_expiry_sort_keeps_fractional_order_and_stable_input_indices(payload):
    one(payload)
    first = payload["futures"][0]
    first["expiry"] = "2026-12-06T08:00:00.500000Z"
    payload["futures"].append(dict(first, instrument_id="earlier", expiry="2026-12-06T08:00:00Z"))
    result = build_crypto_basis(payload)
    assert [row["input_index"] for row in result["rows"]] == [1, 0]


def test_replay_hash_changes_with_policy_source_quote_and_cutoff(payload):
    original = build_crypto_basis(payload)
    assert build_crypto_basis(deepcopy(payload)) == original
    for field, value in (("bid", "99.8"), ("source_ref", "synthetic:other")):
        revised = deepcopy(payload)
        revised["spot"][field] = value
        assert build_crypto_basis(revised)["input_sha256"] != original["input_sha256"]
    payload["policy"]["max_pair_skew_seconds"] += 1
    assert build_crypto_basis(payload)["input_sha256"] != original["input_sha256"]


def test_full_twelve_contract_result_and_tool_pages_are_bounded_complete(payload):
    first = one(payload)["futures"][0]
    payload["futures"] = [dict(first, instrument_id=f"future-{i}", expiry=iso(datetime(2026, 12, 6, 8, tzinfo=timezone.utc) + timedelta(days=i))) for i in range(12)]
    result = build_crypto_basis(payload)
    assert len(json.dumps(result).encode()) < 64000
    tool, offset, found, hashes = CryptoBasisTool(), 0, [], set()
    while offset is not None:
        encoded = tool.execute(payload=payload, offset=offset)
        assert len(encoded) <= 10000
        page = json.loads(encoded)
        assert page["ok"] is True and page["summary"]["accepted"] == 12
        hashes.add(page["input_sha256"])
        found.extend(row["instrument_id"] for row in page["rows"])
        offset = page["paging"]["next_offset"]
    assert len(found) == len(set(found)) == 12
    assert hashes == {result["input_sha256"]}
    assert json.loads(tool.execute(payload=payload, offset=12))["rows"] == []


@pytest.mark.parametrize("offset", [True, -1, 13, "1", 1.5])
def test_tool_invalid_offset_is_json_failure(payload, offset):
    assert json.loads(CryptoBasisTool().execute(payload=payload, offset=offset))["ok"] is False


def test_tool_invalid_shape_does_not_echo_client_values(payload):
    payload["spot"]["bid"] = {"private": "do-not-echo-this"}
    result = CryptoBasisTool().execute(payload=payload)
    assert "do-not-echo-this" not in result
    assert json.loads(result)["ok"] is False


def test_deep_nested_and_unpaired_unicode_are_invalid_json_without_raw_exception(payload):
    nested = payload
    for _ in range(1200):
        nested = {"nested": nested}
    for bad in (nested, dict(payload, extra="\ud800")):
        with pytest.raises(ValueError):
            build_crypto_basis(bad)


def test_serializer_recursion_is_reported_as_invalid_request(payload, monkeypatch):
    def recursion(*args, **kwargs):
        raise RecursionError("synthetic serializer recursion")
    monkeypatch.setattr(domain.json, "dumps", recursion)
    with pytest.raises(ValueError, match="finite JSON values"):
        build_crypto_basis(payload)


def test_tool_schema_readonly_and_unknown_args(payload):
    tool = CryptoBasisTool()
    assert tool.is_readonly is True
    assert tool.deterministic is True
    assert tool.parameters["properties"]["payload"]["properties"]["futures"]["maxItems"] == 12
    assert json.loads(tool.execute(payload=payload, result={"forged": True}))["ok"] is False


def test_bundled_example_bytes_are_inspectable_and_identical():
    bundled = ROOT / "frontend/src/data/research/crypto-basis.example.json"
    assert bundled.read_bytes() == EXAMPLE.read_bytes()
    assert CryptoBasisRequest.model_validate_json(EXAMPLE.read_text(encoding="utf-8")).base == "CASE"
