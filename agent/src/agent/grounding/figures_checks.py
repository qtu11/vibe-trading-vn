"""Declared figure checks for the grounding gate (#1622).

Second slice of the migration off the inline rule list in ``policies.py``:
the malformed-declaration finding and the unsourced-symbol finding, moved
byte-for-byte and declared with stable names. Both read the parsed figures
state the ledger stashes for the duration of a validation walk, which is
what the registry contract means by figure state living on the ledger.
"""

from __future__ import annotations

from typing import Any

from src.agent.grounding.figures import FiguresBlock, _fenced_blocks, _lines_with_offsets
from src.agent.grounding.identity import _scan_symbols
from src.agent.grounding.registry import grounding_check


def _active_block(ledger: Any) -> FiguresBlock:
    block = ledger._active_block
    if block is None:
        raise RuntimeError("figure checks only run inside a validation walk")
    return block


@grounding_check(
    name="figures-block-malformed", phase="declarations", order=0,
    code="figures_block_malformed",
    description="A figures block line could not be read as `value | role | note | ref`.",
)
def _figures_block_malformed(ledger: Any, content: str) -> list[dict[str, Any]]:
    return [
        {
            "code": "figures_block_malformed",
            "line": line_no,
            "claim": raw,
            "value": None,
            "role": None,
            "span": None,
            "symbol": None,
            "reason": "unparseable_declaration",
            "message": (f"figures block line {line_no} could not be read as `value | role | note | ref`: " + raw),
        }
        for line_no, raw in _active_block(ledger).malformed
    ]


@grounding_check(
    name="chart-observed-payload", phase="answer", order=1,
    code="chart_not_observed",
    description="A chart must match the current run's observed first-party payload.",
)
def _chart_observed_payload(ledger: Any, content: str) -> list[dict[str, Any]]:
    return [
        {"code": "chart_not_observed", "value": None, "role": None,
         "span": [start, end], "reason": "untrusted_chart_payload",
         "message": "Chart data was not returned by this run's market tools; fetch an observed chart or remove it."}
        for start, end, info, (body_start, body_end) in _fenced_blocks(content)
        if info == "chart" and content[body_start:body_end].strip() not in ledger._trusted_chart_payloads
    ]


@grounding_check(
    name="unsourced-symbol-figures", phase="answer", order=0,
    code="unsourced_symbol_figures",
    description=(
        "A line pairs a symbol no tool call in this session passed in or "
        "returned with a measured figure, so its only origin is model memory."
    ),
)
def _unsourced_symbol_figures(ledger: Any, content: str) -> list[dict[str, Any]]:
    block = _active_block(ledger)
    figures = ledger._active_figures
    issues: list[dict[str, Any]] = []
    reported: set[str] = set()
    for index, (line, offset) in enumerate(_lines_with_offsets(content)):
        unknown = sorted(
            symbol
            for symbol in _scan_symbols(line) - ledger._session_symbols - reported
            if symbol.rsplit(".", 1)[0] not in ledger._session_symbol_roots
        )
        if not unknown:
            continue
        carried = [figure for figure in figures if figure.line == index and figure.shape == "measured"]
        if not carried:
            continue
        # A figure declared ``cited`` is exempt, since a citation is an origin.
        # A measured cell under a table caption naming a collected ``[S#]`` is
        # likewise cited by the table, even without a per-cell declaration.
        def _cited(figure) -> bool:
            match = block.match(figure.value, figure.percent, figure.digits)
            if match is not None and match.role == "cited":
                return True
            return bool(ledger._visible_cited_sources(figure))

        if all(_cited(figure) for figure in carried):
            continue
        for symbol in unknown:
            reported.add(symbol)
            issues.append(
                {
                    "code": "unsourced_symbol_figures",
                    "symbol": symbol,
                    "value": None,
                    "role": None,
                    "reason": "symbol_never_handled",
                    "claim": line.strip()[:200],
                    "span": [offset, offset + len(line)],
                    "message": (
                        f"No tool call in this session passed in or returned {symbol}, "
                        "yet the answer attaches figures to it. Retrieve it, or report "
                        "it as not retrieved."
                    ),
                }
            )
    return issues
