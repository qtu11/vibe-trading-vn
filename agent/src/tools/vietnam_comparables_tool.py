"""Read-only transport for explicit VN peer valuation inputs."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from src.agent.tools import BaseTool
from src.config.limits import TOOL_RESULT_LIMIT
from src.tools._result_paging import fit_records
from src.tools.vietnam_comparables import VietnamComparablesRequest, build_vietnam_comparables

_REQUEST_SCHEMA = VietnamComparablesRequest.model_json_schema()
_REQUEST_DEFINITIONS = _REQUEST_SCHEMA.pop("$defs", {})


class VietnamComparablesTool(BaseTool):
    name = "vietnam_comparables"
    description = (
        "Compare caller-supplied annual .VN equities using price / (PATMI / weighted-average shares) "
        "and price / (parent equity / current common shares). Explicit peer-selection, evidence, "
        "availability, common price time and corporate-action basis are required. Missing/nonpositive "
        "inputs stay excluded. Returns conditional peer-quantile price scenarios, never a forecast. "
        "No source fetch, issuer verification, trade or justified bank P/B model."
    )
    repeatable = True
    deterministic = True
    parameters = {
        "$defs": _REQUEST_DEFINITIONS,
        "type": "object", "properties": {
            "payload": _REQUEST_SCHEMA,
            "offset": {"type": "integer", "minimum": 0, "default": 0},
        }, "required": ["payload"],
    }

    def execute(self, **kwargs: Any) -> str:
        try:
            offset = kwargs.get("offset", 0)
            if type(offset) is not int or offset < 0:
                raise ValueError("offset must be a nonnegative integer")
            payload = kwargs.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            result = build_vietnam_comparables(payload)
            peers = result.pop("peers")

            def build(page, paging):
                return dict(result, peers=page, paging=paging,
                            aggregate_scope="All supplied peers; paging changes displayed rows only")

            output = fit_records(peers, offset, build, max_records=3)
            if len(output) > TOOL_RESULT_LIMIT:
                raise ValueError("A comparables page exceeds the result budget; shorten evidence locators and basis notes")
            return output
        except ValidationError as exc:
            # Pydantic's default rendering includes user input; return only bounded field paths/reasons.
            errors = [".".join(str(part) for part in item["loc"]) + ": " + item["msg"]
                      for item in exc.errors(include_input=False, include_context=False)[:6]]
            return json.dumps({"ok": False, "error": "Invalid comparables payload", "details": errors}, ensure_ascii=False)
        except (ValueError, ArithmeticError) as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
