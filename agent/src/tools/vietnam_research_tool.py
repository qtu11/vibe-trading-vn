"""Quantitative, evidence-linked research for curated non-financial VN companies."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, localcontext
import json
import re
from typing import Any

from src.agent.tools import BaseTool
from src.config.limits import TOOL_RESULT_LIMIT
from src.tools._result_paging import fit_records
from src.tools.local_financial_statements import load_local_statement

_FIELDS = {
    "income": ("revenue", "gross_profit", "net_income", "cogs"),
    "cashflow": ("cfo", "capex"),
    "balance": ("total_assets", "total_liabilities", "total_equity", "current_assets",
                "current_liabilities", "accounts_receivable", "inventories", "accounts_payable"),
}


def _money(row: dict, name: str) -> tuple[Decimal | None, str | None]:
    fact = row["facts"].get(name)
    if fact is None or fact["value"] is None:
        return None, "missing_fact"
    if fact["unit"] != "VND":
        return None, "expected_VND_unit"
    value = Decimal(fact["value"])
    if abs(value.adjusted()) > 100:
        return None, "numeric_range_exceeded"
    return value * fact["scale"], None


def _display(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return "0" if not value else format(value.normalize(), "f")


def _flow(row: dict, rows: list[dict], period: str) -> dict | None:
    start, end = date.fromisoformat(row["period_start"]), date.fromisoformat(row["period_end"])
    months = (end.year - start.year) * 12 + end.month - start.month + 1
    if period == "annual":
        if row["period"] != "annual":
            return None
        if months != 12 or start.day != 1 or end.day != monthrange(end.year, end.month)[1]:
            raise ValueError("Unsupported annual period geometry; expected twelve complete calendar months")
        return dict(row, _previous=None, _flow_start=start.isoformat())
    if start.day != 1 or end.day != monthrange(end.year, end.month)[1]:
        raise ValueError("Unsupported quarterly period geometry; expected complete calendar months")
    if months == 3 and row["period"] == "quarter":
        return dict(row, _previous=None, _flow_start=start.isoformat())
    cumulative = row["period_basis"] == "year_to_date" or (row["period"] == "annual" and months == 12)
    if not cumulative or months not in {6, 9, 12}:
        raise ValueError("Unsupported quarterly/cumulative period geometry")
    end_month = end.year * 12 + end.month - 1
    quarter_start = date((end_month - 2) // 12, (end_month - 2) % 12 + 1, 1)
    previous_end = (quarter_start - timedelta(days=1)).isoformat()
    previous = [r for r in rows if r["statement"] == row["statement"]
                and r["period_start"] == row["period_start"] and r["period_end"] == previous_end
                and (r["period_basis"] == "year_to_date" or
                     (r["period_basis"] == "standalone" and months == 6))]
    if len(previous) > 1:
        raise ValueError("Ambiguous cumulative predecessor; keep one comparable cadence/basis per period")
    return dict(row, _previous=previous[0] if previous else {}, _flow_start=quarter_start.isoformat())


def _research_period(end: str, flows: dict[str, dict], balances: dict[str, dict]) -> dict:
    evidence: list[dict] = []
    evidence_ids: dict[tuple, str] = {}

    def reference(row):
        fields = ("statement", "period", "period_start", "period_end", "period_basis", "consolidation",
                  "revision", "published_at", "available_at", "retrieved_at", "document_sha256", "source_url", "locator")
        key = tuple(row[field] for field in fields)
        if key not in evidence_ids:
            evidence_ids[key] = f"S{len(evidence) + 1}"
            evidence.append(dict(id=evidence_ids[key], **{field: row[field] for field in fields}))
        return evidence_ids[key]

    inputs = {}

    def add(prefix, row, fields):
        for name in fields:
            value, reason, refs = None, "missing_statement", []
            if row:
                refs.append(reference(row))
                value, reason = _money(row, name)
                previous = row.get("_previous")
                if previous is not None:
                    if not previous:
                        value, reason = None, "missing_cumulative_predecessor"
                    else:
                        refs.append(reference(previous))
                        if previous["revision"] != row["revision"]:
                            value, reason = None, "incomparable_revision"
                        else:
                            prior, prior_reason = _money(previous, name)
                            if value is None or prior is None:
                                value, reason = None, reason or prior_reason
                            else:
                                value -= prior
            inputs[f"{prefix}.{name}"] = {"value": _display(value), "unit": "VND", "reason": reason, "evidence": refs}

    for statement in ("income", "cashflow"):
        add(statement, flows.get(statement), _FIELDS[statement])
    add("balance", balances.get(end), _FIELDS["balance"])
    starts = {row["_flow_start"] for row in flows.values()}
    start = next(iter(starts)) if len(starts) == 1 else None
    opening_date = (date.fromisoformat(start) - timedelta(days=1)).isoformat() if start else None
    add("opening_balance", balances.get(opening_date), _FIELDS["balance"])

    def value(name):
        raw = inputs[name]["value"]
        return Decimal(raw) if raw is not None else None

    metrics = {}

    def metric(name, names, compute, unit="ratio", *, positive=(), nonnegative=(), align=False):
        values = [value(key) for key in names]
        reason = None
        if align and len(starts) != 1:
            reason = "inconsistent_income_cashflow_periods"
        elif any(v is None for v in values):
            reason = "missing_or_incompatible_inputs"
        elif any(values[i] <= 0 for i in positive):
            reason = "denominator_must_be_positive"
        elif any(values[i] < 0 for i in nonnegative):
            reason = "expected_nonnegative_magnitude"
        with localcontext() as ctx:
            ctx.prec = 320 if unit == "VND" else 28
            computed = compute(*values) if reason is None else None
        metrics[name] = {"value": _display(computed), "unit": unit, "inputs": names, "reason": reason}

    metric("net_margin", ["income.net_income", "income.revenue"], lambda n, r: n / r, positive=(1,))
    metric("gross_margin", ["income.gross_profit", "income.revenue"], lambda g, r: g / r, positive=(1,))
    metric("cash_conversion", ["cashflow.cfo", "income.net_income"], lambda c, n: c / n, positive=(1,), align=True)
    metric("free_cash_flow", ["cashflow.cfo", "cashflow.capex"], lambda c, k: c - k, "VND", nonnegative=(1,))
    metric("balance_residual", ["balance.total_assets", "balance.total_liabilities", "balance.total_equity"],
           lambda a, l, e: a - l - e, "VND")
    metric("liabilities_to_assets", ["balance.total_liabilities", "balance.total_assets"], lambda l, a: l / a, positive=(1,))
    metric("current_ratio", ["balance.current_assets", "balance.current_liabilities"], lambda a, l: a / l, positive=(1,))
    for metric_name, field in (("roe", "total_equity"), ("roa", "total_assets")):
        metric(metric_name, ["income.net_income", f"opening_balance.{field}", f"balance.{field}"],
               lambda n, a, b: n / ((a + b) / 2), positive=(1, 2))
    metric("accruals", ["income.net_income", "cashflow.cfo", "opening_balance.total_assets", "balance.total_assets"],
           lambda n, c, a, b: (n - c) / ((a + b) / 2), positive=(2, 3), align=True)
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1 if start else None
    for metric_name, field, denominator in (("dso", "accounts_receivable", "revenue"),
                                            ("dio", "inventories", "cogs"), ("dpo", "accounts_payable", "cogs")):
        metric(metric_name, [f"opening_balance.{field}", f"balance.{field}", f"income.{denominator}"],
               lambda a, b, d: (a + b) / 2 / d * days, "days", positive=(2,), nonnegative=(0, 1), align=True)
    cycle_values = [metrics[key]["value"] for key in ("dso", "dio", "dpo")]
    cycle = Decimal(cycle_values[0]) + Decimal(cycle_values[1]) - Decimal(cycle_values[2]) if all(v is not None for v in cycle_values) else None
    metrics["cash_conversion_cycle"] = {"value": _display(cycle), "unit": "days", "inputs": ["dso", "dio", "dpo"],
                                         "reason": None if cycle is not None else "missing_cycle_inputs"}
    residual = metrics["balance_residual"]["value"]
    return {"period_start": start, "period_end": end, "annualized": False,
            "inputs": inputs, "metrics": metrics, "evidence": evidence,
            "checks": {"balance_sheet": "unknown" if residual is None else "passed" if Decimal(residual) == 0 else "failed"}}


def build_vietnam_research(snapshot: dict, period: str, consolidation: str) -> list[dict]:
    rows = [row for row in snapshot["periods"] if row["consolidation"] == consolidation]
    balances = {}
    for row in rows:
        if row["statement"] == "balance":
            end = row["period_end"]
            if end in balances and balances[end]["available_at"] == row["available_at"]:
                raise ValueError("Ambiguous balance-sheet records at the same availability timestamp")
            if end not in balances or row["available_at"] > balances[end]["available_at"]:
                balances[end] = row
    flows = {}
    for row in rows:
        if row["statement"] not in {"income", "cashflow"}:
            continue
        flow = _flow(row, rows, period)
        if flow is not None:
            key = (row["period_end"], row["statement"])
            if key in flows:
                raise ValueError("Ambiguous standalone and cumulative reports; curate one basis per statement/end")
            flows[key] = flow
    ends = sorted({key[0] for key in flows} or set(balances), reverse=True)
    with localcontext() as ctx:
        # Covers the accepted exponent span, 80-digit facts and 12-digit scale without hiding residuals.
        ctx.prec = 320
        return [_research_period(end, {s: flows[(end, s)] for s in ("income", "cashflow") if (end, s) in flows}, balances)
                for end in ends]


class VietnamResearchTool(BaseTool):
    name = "vietnam_research"
    description = (
        "Build evidence-linked quantitative research for a configured local .VN non-financial company. "
        "Normalize explicit VND units; derive comparable standalone quarters from cumulative filings; "
        "check A=L+E, cash-flow quality and working capital using average balances. "
        "Missing/incompatible inputs stay unknown. No market forecast, data verification or trade action."
    )
    repeatable = True
    parameters = {"type": "object", "properties": {
        "code": {"type": "string", "description": "Configured .VN listing"},
        "as_of": {"type": "string", "description": "ISO timestamp with timezone; default current UTC"},
        "period": {"type": "string", "enum": ["quarter", "annual"], "default": "quarter"},
        "consolidation": {"type": "string", "enum": ["consolidated", "separate"], "default": "consolidated"},
        "offset": {"type": "integer", "minimum": 0, "default": 0},
    }, "required": ["code"]}

    def execute(self, **kwargs: Any) -> str:
        try:
            code = kwargs.get("code", "")
            if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9]{1,12}\.VN", code.strip().upper()):
                raise ValueError("code must be a configured .VN listing")
            code = code.strip().upper()
            period, scope = kwargs.get("period", "quarter"), kwargs.get("consolidation", "consolidated")
            if period not in ("quarter", "annual") or scope not in ("consolidated", "separate"):
                raise ValueError("Invalid period or consolidation")
            offset = kwargs.get("offset", 0)
            if type(offset) is not int or offset < 0:
                raise ValueError("offset must be a nonnegative integer")
            snapshot = load_local_statement(code, None, None, kwargs.get("as_of"))
            reports = build_vietnam_research(snapshot, period, scope)
            metadata = {key: value for key, value in snapshot.items() if key != "periods"}

            def build(page, paging):
                return {"ok": True, "market": "vn", "source": "local_financial_statements", "period": period,
                        "consolidation": scope, "methodology": "non_financial_company_ratios", "paging": paging,
                        "data": {code: dict(metadata, periods=page)},
                        "limitations": ["User-supplied evidence is not independently verified.",
                                        "Issuer industry is not classified; this methodology is not suitable for banks or insurers.",
                                        "Ratios are for the reported period and are not annualized.",
                                        "This is quantitative research, not a valuation or investment recommendation."]}

            output = fit_records(reports, offset, build, max_records=4)
            if len(output) > TOOL_RESULT_LIMIT:
                raise ValueError("A research period exceeds the result budget; shorten source URLs/locators")
            return output
        except (ValueError, ArithmeticError) as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
