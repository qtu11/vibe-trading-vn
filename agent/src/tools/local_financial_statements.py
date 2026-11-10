"""Read curated VN statements from an administrator-configured local JSON file."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

import yaml

from backtest.loaders import local_loader
from src.config.limits import TOOL_RESULT_LIMIT

_MAX_BYTES = 2_000_000
_RECORD_FIELDS = {
    "statement", "period", "period_start", "period_end", "period_basis",
    "consolidation", "published_at", "retrieved_at", "source_url",
    "document_sha256", "locator", "revision", "facts",
}


class StatementSourceNotConfigured(ValueError):
    """No local source is configured for the requested issuer."""

    error_code = "statement_source_not_configured"
    remedy = (
        "This symbol has no configured local statement source. Do not retry this local call. "
        "Search issuer/exchange filings with parallel_web_search, then read the original filing "
        "with read_url or read_document and retain its URL, page, period, scope and units. "
        "Until an original filing is collected, mark that evidence missing and financial figures "
        "from news or aggregators unverified. Do not configure or write a local statement store "
        "from inferred figures."
    )


def _text(value: object, field: str, limit: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} must be a non-empty string (max {limit} characters)")
    return value


def _timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, field, 64))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ValueError(f"{field} must be an ISO timestamp with timezone") from None


def _date(value: object, field: str) -> date:
    try:
        text = _text(value, field, 10)
        if len(text) != 10:
            raise ValueError
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{field} must be YYYY-MM-DD") from None


def _configured_path(code: str) -> Path:
    try:
        config = local_loader._load_config() or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ValueError("Cannot read Data Bridge configuration") from None
    if not isinstance(config, dict):
        raise ValueError("Data Bridge configuration must be an object")
    entries = config.get("financial_statements", [])
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError("financial_statements configuration must be a list of objects")
    matches = [entry for entry in entries if entry.get("symbol") == code]
    if not matches:
        raise StatementSourceNotConfigured("Configure exactly one financial_statements source for this symbol in Data Bridge")
    if len(matches) > 1:
        raise ValueError("Configure exactly one financial_statements source for this symbol in Data Bridge")
    path = Path(_text(matches[0].get("path"), "Configured source path", 4096)).expanduser()
    if not path.is_absolute():
        raise ValueError("Configured financial_statements path must be absolute")
    return path


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not allowed")
        result[key] = value
    return result


def _record(row: object) -> tuple[tuple, datetime, dict]:
    if not isinstance(row, dict) or not _RECORD_FIELDS <= row.keys() or row.keys() - _RECORD_FIELDS - {"available_at"}:
        raise ValueError("Each record must contain exactly the documented financial statement fields")
    for field, choices in (
        ("statement", {"balance", "income", "cashflow", "indicators"}),
        ("period", {"annual", "quarter"}),
        ("period_basis", {"instant", "standalone", "year_to_date"}),
        ("consolidation", {"consolidated", "separate"}),
    ):
        if not isinstance(row[field], str) or row[field] not in choices:
            raise ValueError(f"Invalid {field}")
    start, end = _date(row["period_start"], "period_start"), _date(row["period_end"], "period_end")
    if start > end or (row["period_basis"] == "instant" and start != end):
        raise ValueError("period_start/end are inconsistent with period_basis")
    if (row["statement"] == "balance" and row["period_basis"] != "instant") or (
        row["statement"] in {"income", "cashflow"} and row["period_basis"] == "instant"
    ):
        raise ValueError("period_basis is inconsistent with statement")
    published = _timestamp(row["published_at"], "published_at")
    available = _timestamp(row.get("available_at", row["published_at"]), "available_at")
    retrieved = _timestamp(row["retrieved_at"], "retrieved_at")
    if available < published or retrieved < available or datetime.fromisoformat(row["published_at"]).date() < end:
        raise ValueError("Expected period_end <= publication <= availability <= retrieval")
    source_url = _text(row["source_url"], "source_url", 2048)
    try:
        url = urlsplit(source_url)
        if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
            raise ValueError
    except ValueError:
        raise ValueError("source_url must be an HTTP(S) URL without credentials") from None
    sha = _text(row["document_sha256"], "document_sha256", 64)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
        raise ValueError("document_sha256 must contain 64 hex characters")
    _text(row["locator"], "locator", 512)
    _text(row["revision"], "revision", 128)
    facts = row["facts"]
    if not isinstance(facts, dict) or not 1 <= len(facts) <= 100:
        raise ValueError("facts must contain 1..100 named facts")
    for name, fact in facts.items():
        _text(name, "fact name", 64)
        if not isinstance(fact, dict) or set(fact) != {"value", "unit", "scale"}:
            raise ValueError("Each fact must contain value, unit and scale")
        _text(fact["unit"], "fact unit", 32)
        if type(fact["scale"]) is not int or not 1 <= fact["scale"] <= 10**12:
            raise ValueError("fact scale must be an integer in 1..1000000000000")
        if fact["value"] is not None:
            text = _text(fact["value"], "fact value", 80)
            try:
                if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", text) or not Decimal(text).is_finite():
                    raise InvalidOperation
            except InvalidOperation:
                raise ValueError("fact value must be a finite decimal string or null") from None
    normalized = dict(row, REPORT_DATE=row["period_end"], published_at=published.isoformat(),
                      available_at=available.isoformat(), retrieved_at=retrieved.isoformat(),
                      document_sha256=sha.lower())
    if len(json.dumps(normalized, ensure_ascii=False)) > TOOL_RESULT_LIMIT - 2000:
        raise ValueError("Statement record exceeds tool result budget; reduce facts per statement")
    key = tuple(row[field] for field in ("statement", "period", "period_start", "period_end", "period_basis", "consolidation"))
    return key, available, normalized


def load_local_statement(code: str, statement: str | None, period: str | None, as_of: str | None) -> dict:
    """Select latest eligible whole-record revisions; never fetch or certify a filing."""
    cutoff = _timestamp(as_of, "as_of") if as_of is not None else datetime.now(timezone.utc)
    path = _configured_path(code)
    try:
        with path.open("rb") as stream:
            raw = stream.read(_MAX_BYTES + 1)
    except OSError:
        raise ValueError("Cannot read configured financial_statements file") from None
    if len(raw) > _MAX_BYTES:
        raise ValueError("financial_statements file exceeds 2 MB")
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError("financial_statements file must be valid UTF-8 JSON without duplicate keys") from None
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ValueError("Unsupported financial_statements schema_version (expected 1)")
    if payload.get("symbol") != code or payload.get("venue") not in ("HOSE", "HNX", "UPCOM"):
        raise ValueError("financial_statements file symbol/venue does not match the requested VN listing")
    records = payload.get("records")
    if not isinstance(records, list) or len(records) > 1000:
        raise ValueError("records must be a list with at most 1000 entries")
    selected = {}
    timestamps, revisions = set(), set()
    for index, row in enumerate(records):
        try:
            key, available, normalized = _record(row)
            if (key, available) in timestamps or (key, normalized["revision"]) in revisions:
                raise ValueError("Conflicting statement revision or availability timestamp")
            timestamps.add((key, available))
            revisions.add((key, normalized["revision"]))
        except ValueError as exc:
            raise ValueError(f"Record {index}: {exc}") from None
        if (statement is None or key[0] == statement) and (period is None or key[1] == period) and available <= cutoff:
            if key not in selected or available > selected[key][0]:
                selected[key] = (available, normalized)
    rows = [item[1] for _, item in sorted(selected.items(), reverse=True)]
    rows.sort(key=lambda row: row["period_end"], reverse=True)
    return {
        "symbol": code, "venue": payload["venue"], "schema_version": 1,
        "as_of": cutoff.isoformat(), "source_file_sha256": hashlib.sha256(raw).hexdigest(),
        "verification_status": "user_supplied_unverified", "periods": rows,
    }
