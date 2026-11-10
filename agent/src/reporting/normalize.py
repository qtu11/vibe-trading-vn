"""Normalize model-drafted research payloads into the ResearchReport contract.

The agent loop sends *content*; the schema owns the contract. The model often
sends near-miss shapes (Vietnamese market names, ``publisher`` instead of
``provider``, ``price_history`` as parallel date/close arrays, paragraphs as
``{text, source_ids}`` objects, numeric ``key_stats`` values, charts with 13
categories or ``bars`` as a one-element list). Each near-miss used to fail the
whole export and cost another multi-minute reasoning round -- the 8-round
``SCHEMA_VALIDATION_FAILED`` stall in the screenshot.

This normalizer coerces every observed near-miss deterministically and records
a warning per repair. It never invents business figures: unknown numbers are
never created, dangling ``input_keys`` are pruned (not guessed), and over-long
charts are downsampled from the tail (most recent periods) with a warning.
Anything it cannot repair (missing URLs, numbers absent from collected source
text) still fails with a short actionable message instead of a 50KB error dump.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any

_MARKET_ALIASES = {
    "vietnam": "VN_EQUITY",
    "vn": "VN_EQUITY",
    "vn_equity": "VN_EQUITY",
    "vnequity": "VN_EQUITY",
    "vn-equity": "VN_EQUITY",
    "hose": "VN_EQUITY",
    "hnx": "VN_EQUITY",
    "upcom": "VN_EQUITY",
    "forex": "FOREX",
    "fx": "FOREX",
    "foreign exchange": "FOREX",
    "crypto": "CRYPTO",
    "coin": "CRYPTO",
}

_PARAGRAPH_TEXT_KEYS = ("text", "content", "body", "paragraph", "value")

#: Chapter prefixes the model types into a heading. The renderer already adds
#: its own "06", so "1. Kết luận" renders as "06 1. Kết luận". Only strip a
#: prefix that is clearly numbering: digits/roman numerals followed by
#: punctuation, or an explicit "Chương/Chapter/Phần" word. A year such as
#: "2026 - Triển vọng" is content, not numbering.
_CHAPTER_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"(?:chương|chapter|phần|section|mục)\s+\d{1,2}\s*[.:\-–—]?\s*"
    r"|\d{1,2}\s*[.):]\s+"
    r"|[IVX]{1,5}\s*[.):]\s+"
    r")",
    re.IGNORECASE,
)


def _slug(label: str, fallback: str) -> str:
    decomposed = unicodedata.normalize("NFD", label or "")
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    stripped = stripped.replace("đ", "d").replace("Đ", "d")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", stripped.lower()).strip("_")
    return (slug[:60] or fallback).lower()


def _parse_vi_number(raw: Any) -> float | None:
    """Parse a Vietnamese-formatted numeric string; None when unparseable."""
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None
    text = raw.strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return None
    negative = text.startswith("-")
    if negative:
        text = text[1:]
    try:
        if "," in text and "." in text:
            # 234.500,22 -> thousands dots, decimal comma.
            text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(",", ".")
        elif text.count(".") > 1:
            text = text.replace(".", "")
        elif text.count(".") == 1:
            head, tail = text.split(".")
            # 234.500 (3 digits) reads as thousands; 52.6 reads as decimal.
            if len(tail) == 3 and head and head != "0":
                text = head + tail
        value = float(text)
        return -value if negative else value
    except ValueError:
        return None


def _dedup(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _normalize_sources(payload: dict, warnings: list[str]) -> list[str]:
    sources = payload.get("sources")
    if not isinstance(sources, list):
        return []
    ids: list[str] = []
    for index, src in enumerate(sources):
        if not isinstance(src, dict):
            continue
        if "provider" not in src and "publisher" in src:
            src["provider"] = src.pop("publisher")
        if "published_at" not in src and isinstance(src.get("as_of"), str):
            src["published_at"] = src.pop("as_of")
        if "published_at" not in src and isinstance(src.get("date"), str):
            src["published_at"] = src.pop("date")
        if not src.get("provider"):
            domain = re.sub(r"^https?://(www\.)?", "", str(src.get("url", "")))
            domain = domain.split("/")[0] or "nguồn thu thập"
            src["provider"] = domain[:100]
            warnings.append(f"sources[{index}]: thiếu provider, dùng tạm '{src['provider']}'")
        elif len(str(src["provider"]).strip()) < 2:
            src["provider"] = f"Nguồn {src['provider']} (không tên)"
            warnings.append(f"sources[{index}]: provider quá ngắn, đã làm rõ")
        sid = src.get("id")
        if isinstance(sid, str) and sid:
            ids.append(sid)
    return _dedup(ids)


def _ensure_metric_keys(items: Any, prefix: str, warnings: list[str]) -> list[dict]:
    if not isinstance(items, list):
        return []
    seen: set[str] = set()
    for index, metric in enumerate(items):
        if not isinstance(metric, dict):
            continue
        key = metric.get("key")
        if not isinstance(key, str) or not key.strip():
            generated = _slug(str(metric.get("label", "")), f"{prefix}_{index}")
            base, suffix = generated, 2
            while base in seen:
                base = f"{generated}_{suffix}"
                suffix += 1
            metric["key"] = base
            warnings.append(f"metric '{metric.get('label', index)}': tự sinh key '{base}'")
        if metric["key"] in seen:
            metric["key"] = f"{metric['key']}_{index}"
            warnings.append(f"trùng metric.key, đổi thành '{metric['key']}'")
        seen.add(metric["key"])
        if isinstance(metric.get("value"), str):
            parsed = _parse_vi_number(metric["value"])
            if parsed is not None:
                metric["value"] = parsed
    return items


def _map_top_level_market_price(payload: dict, warnings: list[str]) -> None:
    market_price = payload.get("market_price")
    if not isinstance(market_price, dict):
        return
    financial = payload.get("financial_metrics")
    if not isinstance(financial, list):
        # A non-list here is a shape the model got wrong. Replacing it with
        # an empty list silently discarded whatever the model had sent, and
        # the export then succeeded with the numbers missing -- the report
        # looked complete and the figures were gone. Say so instead.
        if financial is not None:
            warnings.append(
                "financial_metrics không phải danh sách nên bị bỏ qua; "
                "gửi lại dưới dạng mảng các object metric."
            )
        financial = []
        payload["financial_metrics"] = financial
    if any(isinstance(m, dict) and m.get("key") == "market_price" for m in financial):
        return
    entry: dict[str, Any] = {"key": "market_price", "label": "Giá thị trường tham chiếu"}
    for field in ("label", "value", "unit", "as_of", "observed_at", "price_basis",
                  "source_ids", "evidence_kind", "decimals", "note"):
        if field in market_price:
            entry[field] = market_price[field]
    if isinstance(entry.get("value"), str):
        parsed = _parse_vi_number(entry["value"])
        entry["value"] = parsed if parsed is not None else None
    financial.insert(0, entry)
    warnings.append("chuyển market_price ở cấp cao -> financial_metrics['market_price']")


def _normalize_price_history(payload: dict, all_ids: list[str], warnings: list[str]) -> None:
    history = payload.get("price_history")
    if history is None:
        return
    currency = str(payload.get("currency", "") or "").strip()
    market_price_unit, market_price_basis, market_price_sources = "", None, []
    financial = payload.get("financial_metrics") or []
    if isinstance(financial, list):
        for metric in financial:
            if isinstance(metric, dict) and metric.get("key") == "market_price":
                market_price_unit = str(metric.get("unit", "") or "")
                market_price_basis = metric.get("price_basis")
                if isinstance(metric.get("source_ids"), list):
                    market_price_sources = [s for s in metric["source_ids"] if isinstance(s, str)]
                break
    default_unit = market_price_unit or (currency or "VND")
    default_basis = market_price_basis or "raw"
    default_sources = market_price_sources or list(all_ids)

    if isinstance(history, dict):
        dates = history.get("dates") if isinstance(history.get("dates"), list) else []
        closes = history.get("closes") if isinstance(history.get("closes"), list) else []
        volumes = history.get("volumes") if isinstance(history.get("volumes"), list) else []
        dict_sources = history.get("source_ids") if isinstance(history.get("source_ids"), list) else default_sources
        dict_unit = str(history.get("currency") or history.get("unit") or default_unit)
        points = []
        for i, (day, close) in enumerate(zip(dates, closes)):
            point: dict[str, Any] = {"date": day, "close": close, "unit": dict_unit,
                                     "price_basis": default_basis, "source_ids": list(dict_sources)}
            if i < len(volumes):
                point["volume"] = volumes[i]
            points.append(point)
        payload["price_history"] = points
        warnings.append(f"chuyển price_history dạng dates/closes -> {len(points)} điểm PricePoint")
        history = payload["price_history"]

    if isinstance(history, list):
        for point in history:
            if not isinstance(point, dict):
                continue
            if not point.get("unit"):
                point["unit"] = default_unit
            if point.get("price_basis") is None:
                point["price_basis"] = default_basis
            if not point.get("source_ids"):
                point["source_ids"] = list(default_sources)
            if isinstance(point.get("close"), str):
                parsed = _parse_vi_number(point["close"])
                if parsed is not None:
                    point["close"] = parsed


def _extract_text_items(items: Any) -> tuple[list[str], list[str]]:
    """Split a paragraphs/bullets list into plain strings + collected source_ids."""
    texts: list[str] = []
    collected: list[str] = []
    if not isinstance(items, list):
        return texts, collected
    for item in items:
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, dict):
            text = ""
            for key in _PARAGRAPH_TEXT_KEYS:
                if isinstance(item.get(key), str) and item[key].strip():
                    text = item[key]
                    break
            if text:
                texts.append(text)
            sids = item.get("source_ids")
            if isinstance(sids, list):
                collected.extend(s for s in sids if isinstance(s, str))
        elif item is not None:
            texts.append(str(item))
    return texts, _dedup(collected)


def _normalize_chart(chart: Any, warnings: list[str]) -> dict | None:
    if not isinstance(chart, dict) or not chart.get("title"):
        warnings.append("bỏ biểu đồ rỗng (thiếu title)")
        return None
    bars = chart.get("bars")
    if isinstance(bars, list):
        if len(bars) == 1 and isinstance(bars[0], dict):
            chart["bars"] = bars[0]
            warnings.append(f"biểu đồ '{chart.get('title')}': bars dạng list 1 phần tử -> unwrap")
        elif len(bars) > 1 and all(isinstance(b, dict) for b in bars):
            chart["bars"] = bars[0]
            warnings.append(f"biểu đồ '{chart.get('title')}': giữ series đầu làm bars, bỏ {len(bars) - 1} series thừa")
        else:
            warnings.append(f"bỏ biểu đồ '{chart.get('title')}': bars không hợp lệ")
            return None
    categories = chart.get("categories")
    if not isinstance(categories, list) or len(categories) < 2:
        warnings.append(f"bỏ biểu đồ '{chart.get('title')}': cần ít nhất 2 categories")
        return None
    if len(categories) > 8:
        keep = 8
        chart["categories"] = categories[-keep:]
        for part in ("bars", "line", "line_numerator"):
            series = chart.get(part)
            if isinstance(series, dict) and isinstance(series.get("values"), list) and len(series["values"]) > keep:
                series["values"] = series["values"][-keep:]
        warnings.append(f"biểu đồ '{chart.get('title')}': giữ 8 kỳ gần nhất (từ {len(categories)} categories)")
    count = len(chart["categories"])
    for part in ("bars", "line", "line_numerator"):
        series = chart.get(part)
        if isinstance(series, dict) and isinstance(series.get("values"), list):
            values = series["values"]
            if len(values) != count:
                if len(values) > count:
                    series["values"] = values[-count:]
                    warnings.append(f"biểu đồ '{chart.get('title')}': cắt {part} về {count} giá trị")
                else:
                    warnings.append(f"bỏ biểu đồ '{chart.get('title')}': {part} thiếu giá trị ({len(values)}/{count})")
                    return None
    return chart


def _normalize_sections(payload: dict, all_ids: list[str], warnings: list[str]) -> None:
    for field in ("analysis_sections", "appendix_sections"):
        sections = payload.get(field)
        if not isinstance(sections, list):
            continue
        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            heading = section.get("heading")
            if isinstance(heading, str):
                stripped = _CHAPTER_NUMBER_PREFIX_RE.sub("", heading, count=1).strip()
                if stripped and stripped != heading.strip():
                    section["heading"] = stripped
                    warnings.append(f"{field}[{index}]: bỏ số thứ tự chương khỏi heading")
            texts, text_ids = _extract_text_items(section.get("paragraphs"))
            if texts or isinstance(section.get("paragraphs"), list):
                section["paragraphs"] = texts
            bullets, bullet_ids = _extract_text_items(section.get("bullets"))
            if bullets or isinstance(section.get("bullets"), list):
                section["bullets"] = bullets
            collected = _dedup(text_ids + bullet_ids)
            sids = section.get("source_ids")
            if not isinstance(sids, list) or not [s for s in sids if isinstance(s, str) and s]:
                if collected:
                    section["source_ids"] = collected
                elif all_ids:
                    section["source_ids"] = list(all_ids)
                    warnings.append(f"{field}[{index}]: thiếu source_ids, dùng tạm toàn bộ nguồn")
            charts = section.get("charts")
            if isinstance(charts, list):
                kept = []
                for chart in charts:
                    fixed = _normalize_chart(chart, warnings)
                    if fixed is not None:
                        kept.append(fixed)
                section["charts"] = kept[:2]
                if len(charts) > len(kept):
                    warnings.append(f"{field}[{index}]: bỏ {len(charts) - len(kept)} biểu đồ không hợp lệ")


def _walk_evidence(node: Any, metric_keys: set[str], all_ids: list[str], warnings: list[str], path: str = "report") -> None:
    if isinstance(node, dict):
        input_keys = node.get("input_keys")
        if isinstance(input_keys, list) and input_keys:
            pruned = [k for k in input_keys if k in metric_keys]
            dropped = [k for k in input_keys if k not in metric_keys]
            if dropped:
                node["input_keys"] = pruned
                warnings.append(f"{path}: bỏ input_keys không tồn tại {dropped}")
        kind = node.get("evidence_kind")
        sids = node.get("source_ids")
        if isinstance(sids, list) and sids:
            # An id that no collected source carries is a genuine reference
            # error, not a shape problem: the schema must reject it. Only
            # duplicate or non-string entries are pruned here.
            kept = [s for s in sids if isinstance(s, str) and s]
            if len(kept) != len(sids):
                node["source_ids"] = kept
                warnings.append(f"{path}: bỏ source_ids không phải chuỗi")
        elif kind in ("observed", "cited") and ("source_ids" not in node or not isinstance(sids, list)):
            # The model omitted attribution entirely: fall back to all collected
            # sources (numbers are still verified word-by-word downstream).
            if all_ids:
                node["source_ids"] = list(all_ids)
                warnings.append(f"{path}: thiếu source_ids, dùng tạm toàn bộ nguồn")
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                _walk_evidence(value, metric_keys, all_ids, warnings, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            if isinstance(value, (dict, list)):
                _walk_evidence(value, metric_keys, all_ids, warnings, f"{path}[{i}]")


def normalize_report_payload(data: dict) -> tuple[dict, list[str]]:
    """Coerce a near-miss payload into the ResearchReport contract.

    Returns:
        (normalized_payload, warnings). The payload is a deep copy; the input
        is never mutated. Business figures are never invented -- only shapes,
        keys, scales labels and attribution defaults are repaired.
    """
    warnings: list[str] = []
    if not isinstance(data, dict):
        return data, warnings
    payload = copy.deepcopy(data)

    market = payload.get("market")
    if isinstance(market, str):
        mapped = _MARKET_ALIASES.get(market.strip().lower())
        if mapped and mapped != market:
            payload["market"] = mapped
            warnings.append(f"market '{market}' -> '{mapped}'")

    if not payload.get("company_name") and isinstance(payload.get("company"), str):
        payload["company_name"] = payload["company"]
    if not payload.get("company_name") and isinstance(payload.get("symbol"), str):
        payload["company_name"] = payload["symbol"]
        warnings.append("thiếu company_name, dùng tạm symbol")

    if not payload.get("title") and isinstance(payload.get("symbol"), str):
        company = str(payload.get("company_name", payload["symbol"]))
        payload["title"] = f"Phân tích {payload['symbol']} — {company}"[:250]
        warnings.append("tự đặt title mặc định (không bịa số liệu)")
    if not payload.get("subtitle"):
        payload["subtitle"] = f"Báo cáo phân tích {payload.get('exchange', '')} · dữ liệu đến {payload.get('data_as_of', '')}"[:250]
    if not payload.get("overview") and isinstance(payload.get("executive_summary"), str):
        payload["overview"] = payload["executive_summary"][:3500]
        warnings.append("dùng executive_summary làm overview tạm thời")

    all_ids = _normalize_sources(payload, warnings)

    for field, prefix in (("financial_metrics", "metric"), ("valuation_metrics", "valuation")):
        items = payload.get(field)
        if isinstance(items, list):
            _ensure_metric_keys(items, prefix, warnings)

    _map_top_level_market_price(payload, warnings)

    metric_keys = {m.get("key") for m in
                   ([*(payload.get("financial_metrics") or []), *(payload.get("valuation_metrics") or [])])
                   if isinstance(m, dict) and isinstance(m.get("key"), str)}

    data_as_of = payload.get("data_as_of")
    for field in ("financial_metrics", "valuation_metrics"):
        for metric in (payload.get(field) or []):
            if isinstance(metric, dict) and metric.get("value") is not None and not metric.get("as_of") and data_as_of:
                metric["as_of"] = data_as_of
                warnings.append(f"metric '{metric.get('key')}': thiếu as_of, dùng data_as_of")

    for field in ("key_stats", "forecast_stats"):
        stats = payload.get(field)
        if isinstance(stats, list):
            if len(stats) > 8:
                payload[field] = stats[:8]
                warnings.append(f"{field}: giữ 8 mục đầu (từ {len(stats)} mục)")
            for stat in payload[field]:
                if isinstance(stat, dict) and not isinstance(stat.get("value"), str):
                    stat["value"] = str(stat.get("value", ""))[:40]

    _normalize_price_history(payload, all_ids, warnings)
    _normalize_sections(payload, all_ids, warnings)

    # A list field that is not a list is dropped by the schema validator
    # with a bare "Input should be a valid list" that names the field but
    # not what was in it. Report the type the model actually sent, so the
    # retry can send the right shape instead of guessing again.
    for field in (
        "financial_metrics",
        "valuation_metrics",
        "investment_theses",
        "risk_factors",
        "sources",
        "price_history",
        "analysis_sections",
        "appendix_sections",
        "key_stats",
        "forecast_stats",
        "quarterly_results",
        "catalysts",
    ):
        value = payload.get(field)
        if value is None or isinstance(value, list):
            continue
        warnings.append(
            f"{field} phải là một mảng, nhưng nhận được {type(value).__name__}; "
            "trường này sẽ bị bỏ qua."
        )

    # The prose surfaces (overview / executive_summary) carry their own
    # attribution block. Without it the whole report is refused with
    # "Thiếu source_ids: overview" -- one of the stalls in the screenshot.
    for field in ("overview", "executive_summary"):
        text = payload.get(field)
        if not isinstance(text, str) or not text.strip():
            continue
        evidence = payload.get(f"{field}_evidence")
        if not isinstance(evidence, dict):
            evidence = {}
            payload[f"{field}_evidence"] = evidence
        sids = evidence.get("source_ids")
        if not isinstance(sids, list) or not [s for s in sids if isinstance(s, str) and s]:
            evidence["source_ids"] = list(all_ids)
            warnings.append(f"{field}_evidence: thiếu source_ids, dùng tạm toàn bộ nguồn")
        kind = evidence.get("evidence_kind")
        if kind in ("derived", "assumption"):
            if not str(evidence.get("methodology", "")).strip():
                evidence["methodology"] = f"Tổng hợp từ các nguồn đã thu thập trong phiên: {', '.join(all_ids) or 'không có'}"
                warnings.append(f"{field}_evidence: derived thiếu methodology, bổ sung mô tả")
            input_keys = evidence.get("input_keys")
            if not isinstance(input_keys, list) or not input_keys:
                evidence["input_keys"] = []
                evidence["evidence_kind"] = "cited"

    _walk_evidence(payload, metric_keys, all_ids, warnings)

    payload.pop("market_price", None)
    payload.pop("currency", None)
    return payload, warnings
