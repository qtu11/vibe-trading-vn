"""Bounded, read-only macro observations; never a substitute for broker quotes.

URLs and instruments are fixed here, not supplied by the model. Daily releases
keep their observation date independently of retrieval/cache time. Each source
can fail without removing the other observations or minting a zero value.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import csv
from datetime import date, datetime, timedelta, timezone
from io import BytesIO, StringIO
import math
import re
from threading import Lock
import time
from zoneinfo import ZoneInfo

import httpx

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
DXY_URL = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB"
GLD_URL = "https://api.spdrgoldshares.com/api/v1/historical-archive?exchange=NYSE&lang=en&product=gld"
CME_URL = (
    "https://www.cmegroup.com/daily_bulletin/current/"
    "Section02B_Summary_Volume_And_Open_Interest_Metals_Futures_And_Options.pdf"
)
_CACHE = {}
_CACHE_LOCK = Lock()
_MAX_BYTES = 4_000_000


def _download(url, *, params=None):
    # Fixed public data endpoints only; no credentials, caller URLs or shell.
    with httpx.Client(
        timeout=httpx.Timeout(25 if url == FRED_URL else 12, connect=5),
        follow_redirects=True,
        headers={"User-Agent": "Vibe-Trading/0.1.18 research-contact-local"} if url == DXY_URL else {},
    ) as client:
        with client.stream("GET", url, params=params) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > _MAX_BYTES:
                    raise ValueError("Source exceeded the research download limit")
    return bytes(content)


def _finite(value):
    if isinstance(value, bool) or value in (None, "", ".", "N/A", "US Holiday"):
        raise ValueError("Missing numeric observation")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite observation")
    return result


def _dated(rows, today):
    # Missing releases are omitted, never forward-filled or replaced with zero.
    unique = {r["date"]: r for r in rows if date.fromisoformat(r["date"]) <= today}
    return [unique[k] for k in sorted(unique)]


def _series(rows, *, today, unit, stale_days):
    rows = _dated(rows, today)
    if not rows:
        raise ValueError("No dated observations")
    latest = rows[-1]
    age = (today - date.fromisoformat(latest["date"])).days
    result = {
        "status": "stale" if age > stale_days else "ok",
        "unit": unit,
        "as_of": latest["date"],
        "age_days": age,
        "frequency": "daily",
        "intraday": False,
        "latest": latest,
        "observations": len(rows),
        "first_date": rows[0]["date"],
    }
    if "value" in latest:
        changes = {}
        for offset in (1, 5, 20):
            if len(rows) > offset:
                old = rows[-offset - 1]
                changes[str(offset)] = {
                    "from": old["date"],
                    "to": latest["date"],
                    "change": round(latest["value"] - old["value"], 6),
                }
        result["changes_observations"] = changes
    return result


def parse_fred(content, series_id, today):
    rows = []
    for row in csv.DictReader(StringIO(content.decode("utf-8-sig"))):
        try:
            stamp = row.get("observation_date") or row.get("DATE")
            date.fromisoformat(stamp)
            rows.append({"date": stamp, "value": _finite(row[series_id])})
        except (TypeError, KeyError, ValueError):
            continue
    return _dated(rows, today)


def _fred(series_id, today, *, content=None, params=None):
    params = params or {"id": series_id, "cosd": (today - timedelta(days=120)).isoformat(), "coed": today.isoformat()}
    rows = parse_fred(_download(FRED_URL, params=params) if content is None else content, series_id, today)
    # Multi-series CSVs can ignore cosd upstream. Enforce our own boundary too.
    rows = [r for r in rows if date.fromisoformat(r["date"]) >= today - timedelta(days=120)]
    result = _series(rows, today=today, unit="percent" if series_id == "DFII10" else "index_2006_100", stale_days=7)
    result.update(
        {
            "source": "fred",
            "series_id": series_id,
            "source_url": str(httpx.URL(FRED_URL, params=params)),
            "definition_url": f"https://fred.stlouisfed.org/series/{series_id}",
            "publisher": "Federal Reserve Board via FRED",
        }
    )
    if series_id == "DFII10":
        result["meaning"] = (
            "10-year inflation-indexed Treasury constant maturity yield (TIPS real yield), daily percent; not an intraday rate. Changes are percentage points."
        )
    else:
        result["meaning"] = (
            "Fed Nominal Broad US Dollar Index, Jan 2006=100. A separate dollar-strength reference, NOT ICE DXY."
        )
    return result


def _fred_pair(today):
    # One CSV request for both series avoids two concurrent requests to FRED.
    params = {"id": "DFII10,DTWEXBGS", "cosd": (today - timedelta(days=120)).isoformat(), "coed": today.isoformat()}
    content = _download(FRED_URL, params=params)
    series = {}
    for name, code in (("real_yield_10y", "DFII10"), ("broad_usd", "DTWEXBGS")):
        try:
            series[name] = _fred(code, today, content=content, params=params)
        except (TypeError, KeyError, ValueError):
            series[name] = {
                "status": "unavailable",
                "reason": "INVALID_SERIES",
                "value": None,
                "series_id": code,
                "source_url": str(httpx.URL(FRED_URL, params=params)),
            }
    return {"status": "ok", "series": series}


def parse_dxy(payload, today):
    chart = payload["chart"]["result"][0]
    meta = chart["meta"]
    if meta.get("symbol") != "DX-Y.NYB" or meta.get("instrumentType") != "INDEX":
        raise ValueError("Unexpected DXY instrument identity")
    quotes = chart["indicators"]["quote"][0]["close"]
    stamps = chart["timestamp"]
    if len(quotes) != len(stamps):
        raise ValueError("Incomplete DXY observations")
    rows = []
    for stamp, close in zip(stamps, quotes, strict=True):
        day = datetime.fromtimestamp(stamp, ZoneInfo("America/New_York")).date()
        # The provider can include today's changing daily bar. Use completed days.
        if day >= today:
            continue
        try:
            value = _finite(close)
            if value > 0:
                rows.append({"date": day.isoformat(), "value": value})
        except ValueError:
            continue
    return _dated(rows, today)


def _dxy(today):
    import json

    params = {"interval": "1d", "range": "3mo"}
    payload = json.loads(_download(DXY_URL, params=params))
    result = _series(parse_dxy(payload, today), today=today, unit="index_points", stale_days=4)
    result.update(
        {
            "source": "yahoo_finance",
            "symbol": "DX-Y.NYB",
            "source_url": str(httpx.URL(DXY_URL, params=params)),
            "definition_url": "https://developer.ice.com/fixed-income-data-services/catalog/ice-data-indices-currency-indices",
            "meaning": "ICE US Dollar Index as distributed by Yahoo Finance; completed daily closes, not a licensed real-time ICE feed and not an MT5 execution quote.",
        }
    )
    return result


def parse_gld(content, today):
    from openpyxl import load_workbook

    # Parse only the issuer's explicitly named historical table. Never use the
    # bar list PDF (which is on a settlement-date basis) as the archive.
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    rows = []
    try:
        sheet = workbook["US GLD Historical Archive"]
        records = sheet.iter_rows(values_only=True)
        headers = {str(v).strip(): i for i, v in enumerate(next(records))}
        fields = {
            "tonnes": "Tonnes of Gold",
            "ounces": "Total Ounces of Gold in the Trust",
            "ounces_per_share": "Ounces of Gold per Share",
            "nav_per_share": "NAV/Share at 10:30am NYT",
            "share_volume": "Daily Share Volume",
        }
        positions = {k: headers[v] for k, v in fields.items()}
        for record in records:
            try:
                raw_date = record[headers["Date"]]
                stamp = (
                    raw_date.date()
                    if isinstance(raw_date, datetime)
                    else datetime.strptime(str(raw_date), "%d-%b-%Y").date()
                )
                values = {k: _finite(record[i]) for k, i in positions.items()}
                if min(values.values()) < 0 or values["ounces_per_share"] <= 0:
                    continue
                values["estimated_shares"] = round(values["ounces"] / values["ounces_per_share"])
                rows.append({"date": stamp.isoformat(), **values})
            except (ValueError, TypeError, IndexError):
                continue
    finally:
        workbook.close()
    return _dated(rows, today)


def _gld(today):
    rows = parse_gld(_download(GLD_URL), today)[-61:]
    result = _series(rows, today=today, unit="tonnes_of_gold", stale_days=5)
    latest = rows[-1]
    changes = {}
    # Net creations are an ESTIMATE from shares, not the change in AUM, which
    # includes price moves. Never claim this is a global gold-ETF flow dataset.
    for offset in (1, 5, 20):
        if len(rows) > offset:
            old = rows[-offset - 1]
            period = rows[-offset:]
            changes[str(offset)] = {
                "from": old["date"],
                "to": latest["date"],
                "holdings_change_tonnes": round(latest["tonnes"] - old["tonnes"], 4),
                "estimated_net_creation_usd": round(
                    sum(
                        (current["estimated_shares"] - previous["estimated_shares"]) * current["nav_per_share"]
                        for previous, current in zip(rows[-offset - 1 : -1], period, strict=True)
                    ),
                    2,
                ),
            }
    result.update(
        {
            "source": "spdr_gold_shares",
            "symbol": "GLD",
            "source_url": GLD_URL,
            "definition_url": "https://www.spdrgoldshares.com/usa/gld/",
            "changes_observations": changes,
            "meaning": "GLD only: issuer-reported gold holdings and exchange-traded share volume. Share volume is NOT XAUUSD volume. Holdings change is NOT a cash flow.",
            "flow_method": "ESTIMATE: shares=round(total_ounces/ounces_per_share); daily net creations=(shares_t-shares_t-1)*NAV_per_share_t, summed for 5/20 observations. Rounding, fees and corporate actions can affect this proxy. Not issuer-reported cash flow or all-ETF flow.",
        }
    )
    return result


def parse_cme(content, today):
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    text = "\n".join(page.extract_text(extraction_mode="layout") for page in reader.pages[:3])
    # Date must come from the report itself, never the HTTP retrieval date.
    match = re.search(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+([A-Z][a-z]{2})\s+(\d{1,2}),?\s+(20\d{2})", text)
    if not match:
        raise ValueError("CME bulletin date unavailable")
    stamp = datetime.strptime(" ".join(match.groups()), "%b %d %Y").date()
    if stamp > today:
        raise ValueError("Future-dated CME bulletin")
    # Read positions from the printed GC row. Empty open-outcry cells must
    # not shift the overall-volume column: use the layout column headings.
    header = next((line for line in text.splitlines() if "GLOBEX" in line and "OVERALL" in line), "")
    row = next((line for line in text.splitlines() if re.search(r"\bGC\s+COMEX GOLD FUTURES\b", line)), "")
    overall = header.find("OVERALL")
    if overall < 0 or not row:
        raise ValueError("Unrecognized CME GC volume table")
    # The first OVERALL column is OVERALL VOLUME; its cell ends before the
    # next OVERALL (combined open interest) column. Refuse ambiguous layouts.
    end = header.find("OVERALL", overall + 7)
    cell = row[max(0, overall - 3) : end - 3 if end > overall else overall + 16].strip()
    if not re.fullmatch(r"\d[\d,]*", cell):
        raise ValueError("CME overall volume cell could not be verified")
    return {"date": stamp.isoformat(), "value": int(cell.replace(",", ""))}


def _cme(today):
    row = parse_cme(_download(CME_URL), today)
    result = _series([row], today=today, unit="contracts", stale_days=4)
    result.update(
        {
            "source": "cme_group",
            "product": "GC",
            "venue": "COMEX",
            "source_url": CME_URL,
            "meaning": "Published daily OVERALL VOLUME for standard GC gold futures, all listed contract months. Separate centralized futures reference; NOT MT5 CFD volume, not a front-month price or intraday feed.",
        }
    )
    return result


def _cached(name, fetch, today):
    key = (name, today.isoformat())
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and time.monotonic() < hit[0]:
            result = deepcopy(hit[1])
            result["cached"] = True
            return result
    retrieved = datetime.now(timezone.utc).isoformat()
    try:
        result = fetch(today)
    except Exception as exc:
        # No raw response/exception text: these public endpoints need no keys,
        # but network exception text is still not useful model evidence.
        result = {"status": "unavailable", "reason": type(exc).__name__, "value": None}
        if isinstance(exc, httpx.HTTPStatusError):
            result["http_status"] = exc.response.status_code
        result["source_url"] = {
            "dxy": DXY_URL,
            "fred": FRED_URL,
            "real_yield_10y": FRED_URL,
            "broad_usd": FRED_URL,
            "gold_etf": GLD_URL,
            "gold_futures_volume": CME_URL,
        }[name]
    result.update({"retrieved_at": retrieved, "cached": False})
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic() + (60 if result["status"] == "unavailable" else 900), deepcopy(result))
        for old in list(_CACHE):
            if old[1] != today.isoformat():
                del _CACHE[old]
    return result


def get_macro_context(*, gold=True):
    today = datetime.now(ZoneInfo("America/New_York")).date()
    providers = {"dxy": _dxy, "fred": _fred_pair}
    if gold:
        providers.update({"gold_etf": _gld, "gold_futures_volume": _cme})
    with ThreadPoolExecutor(max_workers=len(providers), thread_name_prefix="forex-macro") as pool:
        futures = {name: pool.submit(_cached, name, fetch, today) for name, fetch in providers.items()}
        results = {name: future.result() for name, future in futures.items()}
    fred = results.pop("fred")
    for name in ("real_yield_10y", "broad_usd"):
        series = deepcopy(fred.get("series", {}).get(name, fred))
        series.update({k: fred[k] for k in ("retrieved_at", "cached")})
        results[name] = series
    return results
