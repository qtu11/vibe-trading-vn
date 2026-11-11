"""Paging the same source must retain evidence from shorter later chunks."""

import json

from src.agent.grounding import GroundingLedger


def test_shorter_following_page_keeps_new_figures_under_same_source_id(tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Review the filing")
    for index, text in enumerate(("Operating revenue is 120 VND. " + "Business details. " * 30,
                                  "Net debt is 98765 VND.")):
        ledger.ingest_tool_result(tool_name="read_url", arguments={}, call_id=f"chunk-{index}", success=True,
                                 result=json.dumps({"status": "ok", "url": "https://issuer.example/filing", "content": text}))
    assert len(ledger.sources) == 1
    assert 120 in ledger.sources[0].numbers
    assert 98765 in ledger.sources[0].numbers
