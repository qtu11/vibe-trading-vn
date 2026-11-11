import pytest

from src.swarm.grounding import extract_symbols_from_user_vars


@pytest.mark.parametrize("market", ["Vietnam (HOSE)", "Việt Nam", "HOSE", "HNX", "UPCOM"])
def test_vietnam_market_does_not_promote_target_to_us(market):
    assert extract_symbols_from_user_vars({"target": "TCB", "market": market}) == ["TCB.VN"]


def test_explicit_vietnam_symbols_survive_and_keep_foreign_peers():
    assert extract_symbols_from_user_vars({"target": "TCB.VN and MBB.VN versus DBS.US"}) == ["TCB.VN", "MBB.VN", "DBS.US"]


def test_explicit_foreign_market_symbol_is_not_rewritten_by_vietnam_context():
    assert extract_symbols_from_user_vars({"target": "AAPL.US", "market": "Vietnam"}) == ["AAPL.US"]
