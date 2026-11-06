"""Read-only agent/MCP projection of bounded supplied Crypto basis quotes."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from src.agent.tools import BaseTool
from src.config.limits import TOOL_RESULT_LIMIT
from src.tools._result_paging import fit_records
from src.tools.crypto_basis import CryptoBasisRequest, build_crypto_basis

_SCHEMA = CryptoBasisRequest.model_json_schema()
_DEFINITIONS = _SCHEMA.pop("$defs", {})


class CryptoBasisTool(BaseTool):
    name = "crypto_basis_curve"
    description = (
        "Compare caller-supplied spot and <=12 linear quote-settled dated futures quotes. "
        "Explicit event/availability/expiry times, bid/ask, source refs and age/skew policy are required. "
        "Simple ACT/365F annualization keeps exact UTC fractions; perpetual, stale, skewed and mismatched "
        "rows retain null annualized values and reasons. Gross quoted basis only, never executable yield, "
        "fees/borrow/capital-adjusted carry, verified history, source fetch or trading. Page with offset."
    )
    repeatable = True
    deterministic = True
    parameters = {"$defs": _DEFINITIONS, "type": "object", "properties": {
        "payload": _SCHEMA, "offset": {"type": "integer", "minimum": 0, "maximum": 12, "default": 0},
    }, "required": ["payload"], "additionalProperties": False}

    def execute(self, **kwargs: Any) -> str:
        try:
            if set(kwargs) - {"payload", "offset"}:
                raise ValueError("Only payload and offset are accepted")
            offset = kwargs.get("offset", 0)
            if type(offset) is not int or not 0 <= offset <= 12:
                raise ValueError("offset must be an integer in 0..12")
            result = build_crypto_basis(kwargs.get("payload"))
            rows = result.pop("rows")
            output = fit_records(rows, offset, lambda page, paging: {
                **result, "rows": page, "paging": paging,
                "aggregate_scope": "Summary and input hash cover all supplied contracts; paging only changes displayed rows",
            }, max_records=3)
            if len(output) > TOOL_RESULT_LIMIT:
                raise ValueError("A basis page exceeds the result budget; shorten source references")
            return output
        except ValidationError as exc:
            details = [".".join(str(part) for part in item["loc"]) + ": " + item["msg"]
                       for item in exc.errors(include_input=False, include_context=False)[:6]]
            return json.dumps({"ok": False, "error": "Invalid Crypto basis payload", "details": details}, ensure_ascii=False)
        except (ValueError, ArithmeticError) as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
