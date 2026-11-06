"""Normalize and police the research council's final verdict.

A swarm worker is an LLM like any other: its final report can carry a neat
JSON object with a ``stance`` field and still be unusable — a stop above the
entry for a long, a target below the current price, a position cap with no
evidence, a confidence of 1.4, or prices quoted in a different unit than the
bars the caller observed.  This module turns that report into one normalized
verdict and refuses to call it *actionable* unless the answer is internally
consistent and traceable.

The council runs without the chat session's grounding ledger, so every source
it names is self-reported and stays labelled ``reported_by_council`` here.
Nothing in this module writes into the session source ledger; that separation
is what stops a model-authored URL from laundering an invented number into
citable evidence.

Units
-----
Vietnam quotes stocks in whole VND on the wire (``FPT.VN`` closes at
``63000``) while people and many research notes write thousands (``63,0``).
``parse_number`` accepts both Vietnamese (``1.234,5``) and US (``1,234.5``)
separators, plus the usual ``tỷ`` / ``triệu`` / ``nghìn`` suffixes.  A verdict
whose price fields share one consistent scale that is 1000x away from the
observed bars is rescaled once, explicitly, and the applied scale is returned
so the reader can audit it.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

CONTRACT_VERSION = 1

#: A verdict that is internally consistent but names no source is still
#: displayed, just never as advice: the whole point of the exercise is to
#: stop a prose recommendation from arriving without evidence.
DEFAULT_NAV_VND = 1_000_000_000
VN_BOARD_LOT = 100

_STANCES = {
    "buy": ("MUA", "buy"),
    "add": ("THÊM", "add"),
    "hold": ("GIỮ", "hold"),
    "wait": ("CHỜ", "wait"),
    "avoid": ("TRÁNH", "avoid"),
    "sell": ("BÁN", "sell"),
}
_STANCE_ALIASES = {
    "mua": "buy", "buy": "buy", "long": "buy", "mua vao": "buy",
    "them": "add", "add": "add", "accumulate": "add", "tang ty trong": "add",
    "giu": "hold", "hold": "hold", "nam giu": "hold",
    "cho": "wait", "wait": "wait", "watch": "wait", "theo doi": "wait",
    "tranh": "avoid", "avoid": "avoid", "stay away": "avoid", "khong mua": "avoid",
    "ban": "sell", "sell": "sell", "short": "sell", "giam ty trong": "sell",
}
_BULLISH = {"buy", "add"}
_BEARISH = {"sell", "avoid"}
_TRADE_STANCES = {"buy", "add", "sell"}

#: Suffix multipliers are read only at the end of a value; ``b`` alone is too
#: ambiguous ("5 b" is not a common note) so billion requires ``bn``/``tỷ``.
_SUFFIX_MULTIPLIERS = (
    ("ty", 1e9),
    ("ti", 1e9),
    ("bn", 1e9),
    ("trieu", 1e6),
    ("million", 1e6),
    ("mn", 1e6),
    ("nghin", 1e3),
    ("ngan", 1e3),
    ("thousand", 1e3),
    ("k", 1e3),
)
_CURRENCY_WORDS = (
    "vnd", "vnđ", "đồng", "dong", "usd", "hkd", "cny", "jpy", "krw",
    "sgd", "aud", "cad", "eur", "gbp", "chf", "brl", "inr", "twd",
)
_NUMBER_RE = re.compile(r"[-+]?(?:\d[\d.,]*|\d*[.,]\d+)")
_SUFFIX_PATTERN = (
    r"(?:nghìn|ngàn|triệu|thousand|million|bn|mn|k|K|tỷ|ti|ty)?"
)
_RANGE_RE = re.compile(
    rf"^\s*(?P<low>[-+]?(?:\d[\d.,]*|\d*[.,]\d+)\s*{_SUFFIX_PATTERN})\s*"
    r"(?:-|–|—|~|->|→|to|den|đến|tới)\s*"
    rf"(?P<high>[-+]?(?:\d[\d.,]*|\d*[.,]\d+)\s*{_SUFFIX_PATTERN})\s*$",
    re.IGNORECASE,
)

_MAX_LIST_ITEMS = 12
_MAX_TEXT = 1000
_MAX_SOURCES = 20


def _strip_accents(value: str) -> str:
    """Fold Vietnamese diacritics for tolerant stance matching."""
    text = value.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _text(value: Any, limit: int = _MAX_TEXT) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        try:
            rendered = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return ""
    else:
        rendered = str(value)
    rendered = " ".join(rendered.split()).strip()
    return rendered[:limit]


def _strings(value: Any, *, limit: int = _MAX_LIST_ITEMS) -> list[str]:
    """Normalize a free-form list, accepting bullets, newlines and semicolons."""
    if value is None:
        return []
    if isinstance(value, str):
        pieces = re.split(r"[\n;•]+", value)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        pieces = list(value)
    else:
        pieces = [value]
    out: list[str] = []
    for piece in pieces:
        text = _text(piece, 300)
        text = re.sub(r"^\s*(?:[-*]+|\d+[.)])\s*", "", text)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _suffix_multiplier(text: str) -> float:
    """Return the magnitude suffix multiplier carried by *text* (1 if none)."""
    cleaned = text.strip().rstrip(".").strip()
    lowered = _strip_accents(cleaned).casefold()
    for word in _CURRENCY_WORDS:
        folded = _strip_accents(word).casefold()
        if lowered.endswith(folded):
            cleaned = cleaned[: len(cleaned) - len(folded)].strip()
            lowered = _strip_accents(cleaned).casefold()
            break
    for suffix, factor in _SUFFIX_MULTIPLIERS:
        if lowered.endswith(suffix):
            head = cleaned[: len(cleaned) - len(suffix)].strip()
            # "5k" is fine; "risk" must not lose its tail.
            if not head or not re.search(r"\d", head):
                continue
            if re.search(r"[a-z]", _strip_accents(head[-1]).casefold()):
                continue
            return factor
    return 1.0


def _split_suffix(text: str) -> tuple[str, float]:
    """Remove a trailing magnitude/currency suffix and return its multiplier."""
    multiplier = _suffix_multiplier(text)
    if multiplier == 1.0:
        return text, 1.0
    cleaned = text.strip().rstrip(".").strip()
    lowered = _strip_accents(cleaned).casefold()
    for word in _CURRENCY_WORDS:
        folded = _strip_accents(word).casefold()
        if lowered.endswith(folded):
            cleaned = cleaned[: len(cleaned) - len(folded)].strip()
            lowered = _strip_accents(cleaned).casefold()
            break
    for suffix, factor in _SUFFIX_MULTIPLIERS:
        if factor == multiplier and lowered.endswith(suffix):
            return cleaned[: len(cleaned) - len(suffix)].strip(), multiplier
    return cleaned, multiplier


def _decimal_from_core(core: str) -> float | None:
    """Interpret one numeric core using VN-locale grouping rules."""
    core = core.strip().replace(" ", "").replace("\u00a0", "")
    if not re.fullmatch(r"[-+]?[\d.,]+", core):
        return None
    sign = -1.0 if core.startswith("-") else 1.0
    core = core.lstrip("+-")
    if not core:
        return None
    has_dot, has_comma = "." in core, "," in core
    try:
        if has_dot and has_comma:
            # The right-most separator is the decimal one: 1.234,5 and 1,234.5.
            decimal = "." if core.rfind(".") > core.rfind(",") else ","
            grouping = "," if decimal == "." else "."
            core = core.replace(grouping, "").replace(decimal, ".")
        elif has_comma:
            groups = core.split(",")
            if len(groups) > 1 and all(len(group) == 3 for group in groups[1:]):
                # 1,234 or 1,234,567: US-style thousands.
                if groups[0] != "0":
                    core = "".join(groups)
                else:
                    core = groups[0] + "." + "".join(groups[1:])
            else:
                core = core.replace(",", ".")
        elif has_dot:
            groups = core.split(".")
            if len(groups) > 1 and all(len(group) == 3 for group in groups[1:]):
                # 1.234 / 1.234.567: VN-style thousands. A leading zero keeps
                # the decimal reading (0.125).
                if groups[0] != "0":
                    core = "".join(groups)
            # Otherwise the single dot is already the decimal separator.
        number = float(core)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return sign * number


def parse_number(value: Any, *, vn_locale: bool = True) -> float | None:
    """Parse a council numeric value, accepting VN/US separators and suffixes.

    Args:
        value: Number or string such as ``"63,5"``, ``"1.234,5"``,
            ``"85-92 nghìn"`` (range handled by :func:`parse_range`),
            ``"5% NAV"`` or ``"1,2 tỷ"``.
        vn_locale: Whether a single dot followed by three digits is a
            thousands separator (``63.000`` -> 63000). Defaults to true
            because the council is a Vietnam-equity workflow.

    Returns:
        A finite float, or ``None`` when the text carries no usable number.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("%", " ").replace("₫", " ").replace("$", " ")
    text, multiplier = _split_suffix(text)
    match = _NUMBER_RE.search(text)
    if match is None:
        return None
    core = match.group(0)
    if vn_locale and "." in core and "," not in core:
        groups = core.lstrip("+-").split(".")
        if len(groups) == 2 and len(groups[1]) == 3 and groups[0] != "0":
            core = groups[0] + groups[1]
    number = _decimal_from_core(core)
    if number is None:
        return None
    number *= multiplier
    return number if math.isfinite(number) else None


def parse_range(value: Any) -> tuple[float, float] | None:
    """Parse a numeric interval from a dict, pair or ``"low - high"`` text."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        low = first_number(value, ("low", "min", "from", "lower", "start"))
        high = first_number(value, ("high", "max", "to", "upper", "end"))
        if low is None or high is None:
            return None
        return (low, high) if low <= high else (high, low)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) != 2:
            return None
        low, high = parse_number(value[0]), parse_number(value[1])
        if low is None or high is None:
            return None
        return (low, high) if low <= high else (high, low)
    text = _text(value, 200)
    if not text:
        return None
    # Drop a parenthetical rationale: "61-63 (MA20 support)".
    text = re.sub(r"\([^)]*\)", " ", text).strip()
    matched = _RANGE_RE.match(text)
    shared_multiplier = 1.0
    if matched is None:
        # A suffix on the whole interval ("85-92 nghìn") belongs to both ends.
        text, shared_multiplier = _split_suffix(text)
        matched = _RANGE_RE.match(text)
    if matched:
        low_text = matched.group("low")
        high_text = matched.group("high")
        low_multiplier = _suffix_multiplier(low_text)
        high_multiplier = _suffix_multiplier(high_text)
        low = parse_number(low_text)
        high = parse_number(high_text)
        if low is None or high is None:
            return None
        # "63k-65" means both ends are thousands.
        if low_multiplier == 1.0 and high_multiplier != 1.0:
            low *= high_multiplier
        if high_multiplier == 1.0 and low_multiplier != 1.0:
            high *= low_multiplier
        low, high = low * shared_multiplier, high * shared_multiplier
        return (low, high) if low <= high else (high, low)
    single = parse_number(text)
    return None if single is None else (single, single)


def first_number(value: Mapping[str, Any], keys: Iterable[str]) -> float | None:
    """Return the first parseable value under any of *keys*."""
    for key in keys:
        if key in value:
            parsed = parse_number(value[key])
            if parsed is not None:
                return parsed
    return None


# ---------------------------------------------------------------------------
# Verdict extraction
# ---------------------------------------------------------------------------


def _unwrap(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Accept ``{verdict: {...}}`` and ``{final_verdict: {...}}`` wrappers."""
    if any(str(key).casefold() == "stance" for key in payload):
        return payload
    for key in ("verdict", "final_verdict", "decision", "recommendation"):
        nested = payload.get(key)
        if isinstance(nested, Mapping) and any(
            str(item).casefold() == "stance" for item in nested
        ):
            return nested
    return None


def _json_objects(text: str) -> Iterable[dict[str, Any]]:
    """Yield balanced top-level JSON objects, tolerating prose in between."""
    index, length = 0, len(text)
    while index < length:
        start = text.find("{", index)
        if start < 0:
            return
        depth, in_string, escape = 0, False, False
        closed = False
        for cursor in range(start, length):
            char = text[cursor]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    closed = True
                    candidate = text[start : cursor + 1]
                    try:
                        parsed = json.loads(candidate)
                    except (ValueError, TypeError):
                        parsed = None
                    if isinstance(parsed, dict):
                        yield parsed
                    index = cursor + 1
                    break
        if not closed:
            # An unbalanced brace (a stray "{" in prose) must not pin the
            # scanner to the same offset forever.
            index = start + 1


def extract_verdict(report: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Find the final verdict object in a PM report.

    Fenced JSON is preferred; a balanced-object scan catches the common case
    where the model forgot the fence.  The last object carrying ``stance``
    wins, because a report may first quote the bull case and only then state
    the PM's own verdict.

    Returns:
        ``(verdict, issues)`` — ``verdict`` is the unwrapped object or ``None``.
    """
    issues: list[str] = []
    if not isinstance(report, str) or not report.strip():
        return None, ["verdict_missing: the council report is empty"]

    candidates: list[dict[str, Any]] = []
    for match in re.finditer(r"```(?:json|JSON)?\s*(.*?)\s*```", report, re.DOTALL):
        try:
            parsed = json.loads(match.group(1))
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)
    if not candidates:
        candidates.extend(_json_objects(report))

    for candidate in reversed(candidates):
        unwrapped = _unwrap(candidate)
        if unwrapped is not None:
            return dict(unwrapped), issues
    issues.append("verdict_missing: no JSON object with a 'stance' field was found")
    return None, issues


_COUNCIL_FENCE_RE = re.compile(r"```council\s*(.*?)\s*```", re.DOTALL)


def extract_council_block(value: Any) -> dict[str, Any] | None:
    """Find the ``council`` artifact in a tool result, fence or rendering.

    The ledger needs the observed bars out of the artifact, and the frontend
    needs the whole block.  Accepting every shape the block travels in — the
    parsed tool payload, its ``fence`` string, or the fence text pasted into a
    message — keeps one parser authoritative instead of three drifting copies.

    Args:
        value: Tool payload mapping, JSON string, fence string, or block dict.

    Returns:
        The council block when it carries ``type: "council"``, else ``None``.
    """
    if isinstance(value, Mapping):
        block_type = str(value.get("type") or "").casefold()
        if block_type == "council":
            return dict(value)
        for key in ("fence", "council", "block"):
            nested = value.get(key)
            if isinstance(nested, (str, Mapping)):
                found = extract_council_block(nested)
                if found is not None:
                    return found
        return None

    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()

    for match in _COUNCIL_FENCE_RE.finditer(text):
        try:
            parsed = json.loads(match.group(1))
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict) and str(parsed.get("type") or "").casefold() == "council":
            return parsed

    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, (Mapping, str)):
        found = extract_council_block(parsed)
        if found is not None:
            return found

    for candidate in _json_objects(text):
        if str(candidate.get("type") or "").casefold() == "council":
            return candidate
    return None


# ---------------------------------------------------------------------------
# Observed snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObservedSnapshot:
    """Observed bar facts a verdict is checked against."""

    symbol: str
    last_close: float
    last_date: str | None = None
    window_low: float | None = None
    window_low_date: str | None = None
    window_high: float | None = None
    window_high_date: str | None = None
    source: str | None = None
    currency: str | None = None
    adjustment: str | None = None
    bars: int = 0

    @property
    def low(self) -> float:
        return self.window_low if self.window_low is not None else self.last_close

    @property
    def high(self) -> float:
        return self.window_high if self.window_high is not None else self.last_close

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _issue(code: str, message: str, severity: str = "error") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _position_cap(value: Any) -> tuple[float | None, str | None]:
    """Parse a NAV cap, taking the low end of a stated range."""
    text = _text(value)
    if not text:
        return None, None
    lowered = _strip_accents(text).casefold()
    if "%" not in text and "nav" not in lowered and "tai san" not in lowered:
        # "0.05" is a fraction of NAV; "5" alone is ambiguous but commonly %.
        parsed = parse_number(text)
        if parsed is not None and 0 < parsed <= 1:
            return parsed * 100, "fraction_interpreted_as_percent"
        return parsed, None
    # "3-5% NAV" carries the unit outside the interval, so drop the wording
    # before range parsing or the trailing "NAV" defeats the end anchor.
    cleaned = re.sub(
        r"(?i)\b(?:nav|tài sản|tai san|portfolio|danh mục|danh muc)\b", " ", text
    )
    cleaned = re.sub(r"%", " ", cleaned).strip()
    interval = parse_range(cleaned)
    if interval is None:
        return parse_number(cleaned), None
    low, high = interval
    if low != high:
        return low, f"range_{low:g}-{high:g}_used_low_end"
    return low, None


def evaluate_verdict(
    raw_verdict: Mapping[str, Any] | None,
    *,
    observed: ObservedSnapshot | None = None,
    extraction_issues: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Validate, normalize and score one council verdict.

    Args:
        raw_verdict: Parsed PM JSON object, or ``None`` when extraction failed.
        observed: Observed window the numbers are checked against.
        extraction_issues: Issues raised while locating the verdict.

    Returns:
        A JSON-ready dict with ``verdict``, ``evaluation``, ``issues`` and
        ``actionable``.  ``actionable`` is true only when no error remains and
        at least one source was named.
    """
    issues: list[dict[str, str]] = []
    for message in extraction_issues or ():
        code, _, detail = message.partition(":")
        issues.append(_issue(code.strip() or "verdict_missing", detail.strip() or message))
    if raw_verdict is None:
        return {
            "contract_version": CONTRACT_VERSION,
            "verdict": None,
            "evaluation": {},
            "issues": issues,
            "actionable": False,
            "trade_actionable": False,
        }

    raw = dict(raw_verdict)

    stance_text = _strip_accents(_text(raw.get("stance"))).casefold()
    stance_key = next(
        (
            key
            for key in sorted(_STANCE_ALIASES, key=len, reverse=True)
            if key and key in stance_text
        ),
        None,
    )
    stance = _STANCE_ALIASES.get(stance_key) if stance_key else None
    if stance is None:
        issues.append(_issue("stance_missing", "stance must be one of MUA/THÊM/GIỮ/CHỜ/TRÁNH/BÁN"))
        stance = "wait"

    horizon = _text(raw.get("horizon") or raw.get("time_horizon") or raw.get("khung_thoi_gian"))
    if not horizon:
        issues.append(_issue("horizon_missing", "horizon is required"))

    confidence = parse_number(raw.get("confidence") or raw.get("confidence_pct"))
    confidence_note = None
    if confidence is None:
        words = _strip_accents(_text(raw.get("confidence"))).casefold()
        confidence = {"high": 80.0, "cao": 80.0, "medium": 60.0, "trung binh": 60.0,
                      "low": 40.0, "thap": 40.0}.get(words)
        confidence_note = "confidence_word_mapped_to_number" if confidence else None
    if confidence is None:
        issues.append(_issue("confidence_missing", "confidence is required (0-100 or 0-1)"))
    else:
        if 0 < confidence <= 1 and not (
            isinstance(raw.get("confidence"), str) and "%" in str(raw.get("confidence"))
        ):
            confidence *= 100
            confidence_note = confidence_note or "fraction_interpreted_as_percent"
        if confidence > 100:
            issues.append(_issue("confidence_out_of_range", "confidence above 100 was clamped"))
            confidence = 100.0
        if confidence < 0:
            issues.append(_issue("confidence_out_of_range", "negative confidence was clamped to 0"))
            confidence = 0.0
        if confidence < 40:
            issues.append(_issue("confidence_low", "confidence below 40%", "warning"))

    fair_raw = raw.get("fair_value_range") or raw.get("fair_value") or raw.get("target")
    fair = parse_range(fair_raw)
    if fair_raw is not None and fair is None:
        issues.append(_issue("fair_value_unparseable", "fair_value_range is not a numeric range", "warning"))

    entry_raw = raw.get("entry_zone") or raw.get("entry") or raw.get("buy_zone")
    entry = parse_range(entry_raw)
    if entry_raw is not None and entry is None:
        issues.append(_issue("entry_zone_unparseable", "entry_zone is not a numeric range"))

    stop = parse_number(raw.get("stop") or raw.get("stop_loss"))

    cap_pct, cap_note = _position_cap(
        raw.get("position_cap") or raw.get("position_cap_pct") or raw.get("position_size")
    )
    if cap_pct is not None and (cap_pct <= 0 or cap_pct > 100):
        issues.append(_issue("position_cap_invalid", "position_cap must be a percentage of NAV between 0 and 100"))
        cap_pct = None
    if cap_pct is not None and cap_pct > 10:
        issues.append(_issue("position_cap_high", "position cap above 10% of NAV is unusually concentrated", "warning"))
    if cap_pct is not None and cap_pct > 30:
        issues.append(_issue("position_cap_extreme", "position cap above 30% of NAV is not an investable single-name cap"))

    catalysts = _strings(raw.get("catalysts") or raw.get("catalyst"))
    risks = _strings(raw.get("risks") or raw.get("risk"))
    invalidation = _text(raw.get("invalidation") or raw.get("invalidation_conditions"))
    sources = _normalize_sources(raw.get("sources") or raw.get("references"))

    if stance in _TRADE_STANCES and not catalysts:
        issues.append(_issue("catalysts_missing", "a trade stance needs at least one catalyst", "warning"))
    if not risks:
        issues.append(_issue("risks_missing", "risks must be stated"))
    if stance in _TRADE_STANCES and not invalidation:
        issues.append(_issue("invalidation_missing", "invalidation conditions are required for a trade stance"))
    if not sources:
        issues.append(_issue("sources_missing", "no source was named; advice cannot be issued without evidence"))

    # --- price scaling -----------------------------------------------------
    entry_multiplier = _value_multiplier(entry_raw)
    stop_multiplier = _value_multiplier(raw.get("stop") or raw.get("stop_loss"))
    fair_multiplier = _value_multiplier(fair_raw)
    explicit_multipliers = {
        value for value in (entry_multiplier, stop_multiplier, fair_multiplier)
        if value != 1.0
    }
    scale, scale_note = 1.0, None

    def compatible(interval: tuple[float, float], anchor: float) -> bool:
        return 0.15 * anchor <= interval[0] and interval[1] <= 6.0 * anchor

    if len(explicit_multipliers) > 1:
        issues.append(_issue(
            "price_units_conflict",
            "price fields mix different magnitude suffixes (e.g. nghìn and tỷ); restate them in one unit",
        ))
    elif len(explicit_multipliers) == 1:
        explicit = next(iter(explicit_multipliers))
        anchors: list[float] = []
        if entry is not None and entry_multiplier != 1.0:
            anchors.extend(entry)
        if stop is not None and stop_multiplier != 1.0:
            anchors.append(stop)
        if fair is not None and fair_multiplier != 1.0:
            anchors.extend(fair)
        anchor = sorted(anchors)[len(anchors) // 2] if anchors else None
        reconciled = False
        conflict = False
        if anchor:
            if entry is not None and entry_multiplier == 1.0 and not compatible(entry, anchor):
                scaled = (entry[0] * explicit, entry[1] * explicit)
                if compatible(scaled, anchor):
                    entry, reconciled = scaled, True
                else:
                    conflict = True
            if stop is not None and stop_multiplier == 1.0 and not (
                0.15 * anchor <= stop <= 6.0 * anchor
            ):
                if 0.15 * anchor <= stop * explicit <= 6.0 * anchor:
                    stop, reconciled = stop * explicit, True
                else:
                    conflict = True
            if fair is not None and fair_multiplier == 1.0 and not compatible(fair, anchor):
                scaled = (fair[0] * explicit, fair[1] * explicit)
                if compatible(scaled, anchor):
                    fair, reconciled = scaled, True
                else:
                    conflict = True
        if conflict:
            issues.append(_issue(
                "price_units_conflict",
                "entry, stop or target cannot be reconciled to one price unit",
            ))
        elif reconciled:
            scale = explicit
            scale_note = (
                f"bare price fields were restated in the {explicit:g}x unit used "
                "by the other verdict fields"
            )
    else:
        price_candidates = [value for value in (
            entry[0] if entry else None,
            entry[1] if entry else None,
            stop,
            fair[0] if fair else None,
            fair[1] if fair else None,
        ) if value is not None]
        scale, scale_note = _detect_scale(price_candidates, observed)
        if scale != 1.0:
            entry = _scale_range(entry, scale)
            fair = _scale_range(fair, scale)
            stop = None if stop is None else stop * scale
    if scale != 1.0 and scale_note:
        issues.append(_issue(
            "price_scale_normalized",
            scale_note,
            "warning",
        ))

    # --- structural rules --------------------------------------------------
    if entry is not None and entry[0] == entry[1]:
        entry = (entry[0], entry[1])

    if stance in _BULLISH or stance == "sell":
        if entry is None:
            issues.append(_issue("entry_zone_missing", "a trade stance needs an entry zone"))
        if stop is None:
            issues.append(_issue("stop_missing", "a trade stance needs a stop"))
    if stance in _TRADE_STANCES and fair is None:
        issues.append(_issue("fair_value_missing", "a trade stance needs a fair-value/target range"))

    if entry is not None and stop is not None:
        if stance in _BULLISH and stop >= entry[0]:
            issues.append(_issue(
                "stop_on_wrong_side",
                f"stop {stop:g} must be below the entry zone low {entry[0]:g} for a long",
            ))
        if stance == "sell" and stop <= entry[1]:
            issues.append(_issue(
                "stop_on_wrong_side",
                f"stop {stop:g} must be above the entry zone high {entry[1]:g} for a short",
            ))

    if fair is not None and entry is not None and stance in _TRADE_STANCES:
        entry_mid = (entry[0] + entry[1]) / 2
        if stance in _BULLISH and fair[1] <= entry_mid:
            issues.append(_issue(
                "fair_value_not_above_entry",
                "the target range must be above the entry midpoint for a long",
            ))
        if stance == "sell" and fair[0] >= entry_mid:
            issues.append(_issue(
                "fair_value_not_below_entry",
                "the target range must be below the entry midpoint for a short",
            ))

    observed_range = None
    if observed is not None:
        observed_range = {
            "low": observed.low,
            "high": observed.high,
            "last_close": observed.last_close,
            "last_date": observed.last_date,
            "window_low_date": observed.window_low_date,
            "window_high_date": observed.window_high_date,
            "bars": observed.bars,
        }
        span = max(observed.high - observed.low, observed.last_close * 0.02, 1e-9)
        if entry is not None:
            edge = 0.25 * span
            if entry[1] < observed.low - edge or entry[0] > observed.high + edge:
                issues.append(_issue(
                    "entry_zone_outside_observed",
                    (
                        f"entry zone {entry[0]:g}-{entry[1]:g} is outside the observed "
                        f"window {observed.low:g}-{observed.high:g}"
                    ),
                ))
            elif entry[1] < observed.low or entry[0] > observed.high:
                issues.append(_issue(
                    "entry_zone_extends_beyond_observed",
                    "entry zone lies outside the observed high/low window",
                    "warning",
                ))
        if stop is not None and entry is not None:
            risk = abs((entry[0] + entry[1]) / 2 - stop)
            reference = (entry[0] + entry[1]) / 2 or 1.0
            distance = risk / reference * 100
            if distance > 35:
                issues.append(_issue(
                    "stop_too_wide",
                    f"stop distance is {distance:.1f}% of entry; consider a tighter invalidation",
                    "warning",
                ))
            elif distance < 0.5:
                issues.append(_issue(
                    "stop_too_tight",
                    f"stop distance is {distance:.2f}% of entry and may be inside normal noise",
                    "warning",
                ))

    # --- deterministic evaluation -----------------------------------------
    evaluation: dict[str, Any] = {
        "observed_window": observed_range,
        "price_scale": scale,
        "price_scale_note": scale_note,
        "confidence_note": confidence_note,
        "position_cap_note": cap_note,
        "entry_mid": None,
        "risk_per_share": None,
        "reward_per_share": None,
        "risk_reward": None,
        "stop_distance_pct": None,
        "sizing": None,
    }
    if entry is not None:
        evaluation["entry_mid"] = round((entry[0] + entry[1]) / 2, 4)
    if entry is not None and stop is not None:
        risk = abs((entry[0] + entry[1]) / 2 - stop)
        evaluation["risk_per_share"] = round(risk, 4)
        evaluation["stop_distance_pct"] = (
            round(risk / max((entry[0] + entry[1]) / 2, 1e-9) * 100, 4)
        )
        if fair is not None:
            if stance in _BULLISH:
                reward = fair[0] - (entry[0] + entry[1]) / 2
            elif stance == "sell":
                reward = (entry[0] + entry[1]) / 2 - fair[1]
            else:
                reward = abs(fair[0] - (entry[0] + entry[1]) / 2)
            evaluation["reward_per_share"] = round(reward, 4)
            evaluation["risk_reward"] = (
                round(reward / risk, 4) if risk > 0 else None
            )
        evaluation["sizing"] = _sizing(
            entry_mid=(entry[0] + entry[1]) / 2,
            risk_per_share=risk,
            cap_pct=cap_pct,
            currency=(observed.currency if observed else None),
        )

    error_codes = [item["code"] for item in issues if item["severity"] == "error"]
    actionable = not error_codes and bool(sources)
    trade_actionable = actionable and stance in _TRADE_STANCES

    verdict = {
        "stance": stance,
        "stance_label": _STANCES[stance][0],
        "horizon": horizon,
        "confidence_pct": confidence,
        "fair_value": {"low": fair[0], "high": fair[1]} if fair else None,
        "entry_zone": {"low": entry[0], "high": entry[1]} if entry else None,
        "stop": stop,
        "position_cap_pct": cap_pct,
        "catalysts": catalysts,
        "risks": risks,
        "invalidation": invalidation,
        "sources": sources,
        "verification": "reported_by_council",
        "reported_chart_ignored": bool(raw.get("chart")),
    }

    return {
        "contract_version": CONTRACT_VERSION,
        "verdict": verdict,
        "evaluation": evaluation,
        "issues": issues,
        "actionable": actionable,
        "trade_actionable": trade_actionable,
        "blocked_reason": "; ".join(error_codes) if error_codes else None,
    }


def _value_multiplier(value: Any) -> float:
    """Return the explicit magnitude multiplier written in a price field."""
    if value is None or isinstance(value, bool):
        return 1.0
    if isinstance(value, (int, float)):
        return 1.0
    if isinstance(value, Mapping):
        multipliers = [_value_multiplier(item) for item in value.values()]
        return max(multipliers, default=1.0)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        multipliers = [_value_multiplier(item) for item in value]
        return max(multipliers, default=1.0)
    text = str(value)
    parts = re.split(r"\s*(?:-|–|—|~|->|→|to|đến|tới)\s*", text)
    return max((_suffix_multiplier(part) for part in parts), default=1.0)


def _scale_range(
    interval: tuple[float, float] | None, scale: float
) -> tuple[float, float] | None:
    if interval is None:
        return None
    return (interval[0] * scale, interval[1] * scale)


def _detect_scale(
    values: Sequence[float], observed: ObservedSnapshot | None
) -> tuple[float, str | None]:
    """Detect a single 1000x unit mismatch between verdict and observed bars."""
    if observed is None or not values:
        return 1.0, None
    verdict_mid = sorted(values)[len(values) // 2]
    observed_mid = observed.midpoint
    if verdict_mid <= 0 or observed_mid <= 0:
        return 1.0, None
    ratio = observed_mid / verdict_mid
    exponent = round(math.log10(ratio)) if ratio > 0 else 0
    if exponent == 0:
        return 1.0, None
    scale = 10.0 ** exponent
    scaled_mid = verdict_mid * scale
    # Only accept a rescale when it lands the verdict in the observed
    # neighbourhood. An arbitrary 1000x jump that still misses the window is a
    # data problem, not a unit convention.
    if 0.35 * observed.low <= scaled_mid <= 3.0 * observed.high:
        return scale, (
            f"verdict prices were quoted at 10^{exponent} of the observed unit; "
            f"rescaled by {scale:g} to whole {observed.currency or 'price'} units"
        )
    return 1.0, None


def _sizing(
    *,
    entry_mid: float,
    risk_per_share: float,
    cap_pct: float | None,
    currency: str | None,
) -> dict[str, Any]:
    """Compute deterministic 1%/2% risk sizing and the NAV cap binding."""
    if entry_mid <= 0 or risk_per_share <= 0:
        return {"available": False, "reason": "entry and stop must define a positive risk"}
    nav = DEFAULT_NAV_VND
    lot = VN_BOARD_LOT if (currency or "VND").upper() == "VND" else 1

    def bucket(pct: float) -> dict[str, Any]:
        budget = nav * pct / 100
        raw_shares = budget / risk_per_share
        shares = math.floor(raw_shares / lot) * lot
        value = shares * entry_mid
        return {
            "risk_pct": pct,
            "risk_budget": round(budget, 2),
            "raw_shares": round(raw_shares, 2),
            "shares": int(shares),
            "position_value": round(value, 2),
        }

    one, two = bucket(1.0), bucket(2.0)
    cap = None
    if cap_pct is not None:
        cap_value = nav * cap_pct / 100
        shares = math.floor(cap_value / entry_mid / lot) * lot
        cap = {
            "cap_pct": cap_pct,
            "cap_value": round(cap_value, 2),
            "shares": int(shares),
            "position_value": round(shares * entry_mid, 2),
        }

    if cap is not None and cap["shares"] < one["shares"]:
        binding = "position_cap"
    elif one["shares"] <= 0:
        binding = "no_lot_size"
    else:
        binding = "risk_1pct"
    return {
        "available": True,
        "currency": (currency or "VND").upper(),
        "nav_assumption": nav,
        "lot_size": lot,
        "risk_1pct": one,
        "risk_2pct": two,
        "position_cap": cap,
        "binding": binding,
        "note": (
            "Illustrative sizing only: assumes NAV of "
            f"{nav:,} {currency or 'VND'}, no slippage, fees or taxes, "
            "and a stop that fills at its trigger."
        ),
    }


def _normalize_sources(value: Any) -> list[dict[str, Any]]:
    """Normalize self-reported sources without pretending they are verified."""
    if value is None:
        return []
    if isinstance(value, (str, Mapping)):
        value = [value]
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if len(out) >= _MAX_SOURCES:
            break
        if isinstance(item, str):
            source = {"title": _text(item, 400)}
        elif isinstance(item, Mapping):
            source = {
                "ref": _text(item.get("ref") or item.get("id") or item.get("source_id"), 40) or None,
                "title": _text(
                    item.get("title") or item.get("name") or item.get("publisher") or item.get("source"),
                    400,
                ),
                "url": _text(item.get("url") or item.get("link"), 600) or None,
                "publisher": _text(item.get("publisher"), 160) or None,
                "published_at": _text(item.get("published_at") or item.get("date"), 60) or None,
                "tier": _text(item.get("tier"), 40) or None,
            }
        else:
            continue
        key = json.dumps(source, ensure_ascii=False, sort_keys=True)
        if key in seen or not (source.get("title") or source.get("url") or source.get("ref")):
            continue
        seen.add(key)
        source["verification"] = "reported_by_council"
        out.append(source)
    return out


__all__ = [
    "CONTRACT_VERSION",
    "DEFAULT_NAV_VND",
    "ObservedSnapshot",
    "evaluate_verdict",
    "extract_council_block",
    "extract_verdict",
    "parse_number",
    "parse_range",
]
