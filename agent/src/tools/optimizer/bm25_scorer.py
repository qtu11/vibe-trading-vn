"""BM25-FSB (Financial Salience Boosting) Scoring Engine.

Combines pure Python BM25 Okapi core with bilingual (Vietnamese/English) financial
tokenization, compound n-gram detection, ticker symbol case preservation,
financial salience boosting (+ticker, +fiscal period, +metric density, +tables),
and boilerplate noise penalties.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, List, Optional, Set, Tuple

from src.tools.optimizer.chunker import Chunk

# Bilingual financial compound phrases (N-grams) to treat as single lexical units
COMPOUND_FINANCIAL_NGRAMS: tuple[str, ...] = (
    # Vietnamese financial compounds
    "doanh thu thuần",
    "doanh thu hoạt động",
    "lợi nhuận sau thuế",
    "lợi nhuận trước thuế",
    "lợi nhuận gộp",
    "biên lợi nhuận gộp",
    "biên lợi nhuận ròng",
    "biên gộp",
    "biên ròng",
    "tăng trưởng tín dụng",
    "tỷ lệ nợ xấu",
    "nợ xấu",
    "lãi suất tái cấp vốn",
    "lãi suất điều hành",
    "lưu chuyển tiền tệ",
    "dòng tiền thuần",
    "dòng tiền tự do",
    "tổng tài sản",
    "vốn chủ sở hữu",
    "vốn điều lệ",
    "giá trị vốn hóa",
    "thu nhập trên mỗi cổ phiếu",
    "kết quả kinh doanh",
    "báo cáo tài chính",
    "kế hoạch kinh doanh",
    "chi phí quản lý",
    "chi phí tài chính",
    "chi phí bán hàng",
    "dự phòng rủi ro",
    "giá trị sổ sách",
    "tỷ suất cổ tức",
    # English financial compounds
    "net income",
    "operating income",
    "operating cash flow",
    "free cash flow",
    "gross margin",
    "operating margin",
    "net margin",
    "earnings per share",
    "price to earnings",
    "debt to equity",
    "working capital",
    "capital expenditure",
    "return on equity",
    "return on assets",
    "cash flow",
    "balance sheet",
    "income statement",
)

# Boilerplate patterns for advertising, cookie consent, terms, copyright
BOILERPLATE_REGEXES: tuple[re.Pattern[str], ...] = (
    re.compile(r"chính\s*sách\s*bảo\s*mật|chinh\s*sach\s*bao\s*mat", re.IGNORECASE),
    re.compile(r"điều\s*khoản\s*sử\s*dụng|dieu\s*khoan\s*su\s*dung", re.IGNORECASE),
    re.compile(r"liên\s*hệ\s*quảng\s*cáo|lien\s*he\s*quang\s*cao", re.IGNORECASE),
    re.compile(r"bản\s*quyền\s*thuộc\s*về|ban\s*quyen\s*thuoc\s*ve", re.IGNORECASE),
    re.compile(r"đăng\s*ký\s*nhận\s*tin|dang\s*ky\s*nhan\s*tin", re.IGNORECASE),
    re.compile(r"tải\s*ứng\s*dụng\s*ngay|tai\s*ung\s*dung\s*ngay", re.IGNORECASE),
    re.compile(r"chia\s*sẻ\s*bài\s*viết|chia\s*se\s*bai\s*viet", re.IGNORECASE),
    re.compile(r"toàn\s*bộ\s*bản\s*quyền|toan\s*bo\s*ban\s*quyen", re.IGNORECASE),
    re.compile(r"privacy\s+policy", re.IGNORECASE),
    re.compile(r"terms\s+of\s+(?:service|use)", re.IGNORECASE),
    re.compile(r"all\s+rights\s+reserved", re.IGNORECASE),
    re.compile(r"copyright\s+(?:©|\(c\))", re.IGNORECASE),
    re.compile(r"subscribe\s+to\s+newsletter", re.IGNORECASE),
    re.compile(r"advertisement", re.IGNORECASE),
    re.compile(r"cookie\s+policy", re.IGNORECASE),
)

# Quantitative financial measurement metric pattern
_METRIC_PATTERN = re.compile(
    r"[-+]?\d+(?:[.,]\d+)?\s*(?:tỷ(?:\s*đồng)?|ty(?:\s*dong)?|triệu(?:\s*USD|\s*đồng)?|trieu(?:\s*USD|\s*dong)?|"
    r"nghìn\s*tỷ|nghin\s*ty|ngàn\s*tỷ|ngan\s*ty|%|điểm|diem|lần|lan|bps|cổ\s*phiếu|co\s*phieu|cp|"
    r"USD|VND|đồng|dong|tấn|tan|người|nguoi|tài\s*khoản|tai\s*khoan|tỷ\s*VND|ty\s*VND)",
    re.IGNORECASE,
)

# Fiscal period patterns (e.g. Q3/2024, 9T/2024, quý III/2024, YoY, MoM, năm 2024)
#
# Vietnamese articles write the quarter as a Roman numeral ("quý III") more
# often than as a digit. Without this form, a quarter label is missed and
# the figures around it lose their period.
#
# A cumulative period ("lũy kế 9 tháng") is its own period. A nine-month
# revenue and a third-quarter revenue are different figures, and when they
# share one label the reconciliation has to throw one of them away.
_PERIOD_PATTERN = re.compile(
    r"\b(?:Q[1-4](?:[/-]?20\d{2})?|"
    r"quý\s+(?:[1-4]|I{1,3}|IV)(?:\s+năm|\s*/)?\s*20\d{2}|"
    r"quý\s+(?:[1-4]|I{1,3}|IV)(?!\s*/\s*\d)|"
    r"[1-9]T(?:[/-]?20\d{2})?|"
    r"lũy\s+kế\s+\d{1,2}\s+tháng(?:\s+đầu\s+năm)?|"
    r"YoY|MoM|QoQ|YTD|FY20\d{2}|năm\s+20\d{2}|20\d{2})\b",
    re.IGNORECASE,
)

# Standard bilingual tokenizer regex matching ticker tokens and alphanumeric words
_TOKEN_REGEX = re.compile(r"(?u)\b[A-Z0-9_\-\.\%]{2,}\b|[\w\d]+", re.UNICODE)

# Pre-sort compound n-grams longest-first so longer phrases are matched before shorter sub-phrases
_SORTED_FINANCIAL_NGRAMS: tuple[str, ...] = tuple(
    sorted(COMPOUND_FINANCIAL_NGRAMS, key=len, reverse=True)
)


def tokenize_financial_text(text: str) -> list[str]:
    """Bilingual financial tokenizer preserving ticker case and compound n-grams."""
    if not text:
        return []

    processed = text

    # Step 1: Detect and join compound n-grams with underscores (longest first)
    for phrase in _SORTED_FINANCIAL_NGRAMS:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        replacement = phrase.lower().replace(" ", "_")
        processed = pattern.sub(replacement, processed)

    # Step 2: Extract tokens
    matches = _TOKEN_REGEX.findall(processed)
    tokens: list[str] = []

    for m in matches:
        # Preserve uppercase tickers (e.g. HPG, VIC, VNM, NVDA, AAPL)
        if m.isupper() and 2 <= len(m) <= 5:
            tokens.append(m)
        else:
            tokens.append(m.lower())

    return tokens


# Common financial acronyms that should not be mistaken for stock tickers
NON_TICKER_ACRONYMS: frozenset[str] = frozenset({
    "EPS", "PE", "PB", "ROE", "ROA", "ROIC", "EBITDA", "EBIT", "CAGR",
    "YOY", "MOM", "QOQ", "YTD", "USD", "VND", "EUR", "GBP", "JPY", "CNY",
    "BPS", "DCF", "NAV", "IPO", "CEO", "CFO", "COO", "CTCK", "BCTC", "KQKD",
    "LNST", "LNTT", "DTT", "TNC", "GDP", "CPI", "FDI", "SBV", "FED", "SEC",
    "HOSE", "HNX", "UPCOM", "VSDC", "GSO", "SSC", "CP", "LLC", "JSC",
})


def extract_tickers_from_query(query: str, extra_tickers: Optional[list[str]] = None) -> list[str]:
    """Extract distinct uppercase stock ticker symbols from a search query."""
    found: set[str] = set()

    if extra_tickers:
        for t in extra_tickers:
            if t and t.strip():
                sym = t.strip().upper()
                if sym not in NON_TICKER_ACRONYMS:
                    found.add(sym)

    # Find 2-5 letter all-caps words in query
    matches = re.findall(r"\b[A-Z]{2,5}\b", query)
    for m in matches:
        sym = m.upper()
        if sym not in NON_TICKER_ACRONYMS:
            found.add(sym)

    return sorted(list(found))


def extract_periods_from_text(text: str) -> list[str]:
    """Extract normalized fiscal periods and years from text."""
    matches = _PERIOD_PATTERN.findall(text)
    return [m.lower().replace(" ", "") for m in matches]


def _extract_scoring_text(chunk: Chunk) -> str:
    """Extract relevant chunk content without ancestor/root breadcrumb leakage.

    Preserves leaf section heading and chunk body while preventing ancestor
    headings and document titles from leaking into every chunk.
    """
    body_text = chunk.raw_content if chunk.raw_content else chunk.content
    if not chunk.raw_content and body_text.startswith("[Section:"):
        body_text = re.sub(r"^\[Section:[^\]]+\]\s*", "", body_text).strip()

    # Extract leaf section heading from breadcrumb if available
    leaf_heading = ""
    if chunk.breadcrumb and chunk.breadcrumb.startswith("[Section:"):
        inner = chunk.breadcrumb[len("[Section:"):].rstrip("]").strip()
        parts = [p.strip() for p in inner.split(" > ") if p.strip()]
        if len(parts) > 1:
            leaf_heading = parts[-1]
        elif len(parts) == 1 and parts[0] != "General":
            leaf_heading = parts[0]

    if leaf_heading and leaf_heading not in body_text:
        return f"{leaf_heading}\n{body_text}"
    return body_text


class BM25FSBScorer:
    """BM25 Okapi core with Financial Salience Boosting (BM25-FSB)."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def score_chunks(
        self,
        chunks: list[Chunk],
        query: str,
        tickers: Optional[list[str]] = None,
        discard_non_positive: bool = True,
    ) -> list[Chunk]:
        """Compute BM25-FSB scores for all chunks in the document.

        Formula:
            FinalScore(D, Q) = Score_BM25(D, Q) + SalienceBoost(D, Q) - BoilerplatePenalty(D)
        """
        if not chunks:
            return []

        # 1. Prepare query tokens and targeted financial entities
        query_tokens = tokenize_financial_text(query)
        target_tickers = extract_tickers_from_query(query, extra_tickers=tickers)
        query_periods = set(extract_periods_from_text(query))

        # 2. Tokenize chunks and collect corpus statistics
        N = len(chunks)
        chunk_tokens_list: list[list[str]] = []
        doc_lengths: list[int] = []
        term_doc_counts: dict[str, int] = {}
        chunk_scoring_texts: list[str] = []

        for chunk in chunks:
            s_text = _extract_scoring_text(chunk)
            chunk_scoring_texts.append(s_text)
            c_tokens = tokenize_financial_text(s_text)
            chunk_tokens_list.append(c_tokens)
            doc_lengths.append(len(c_tokens))

            # Unique terms in this chunk for IDF calculation
            unique_terms = set(c_tokens)
            for term in unique_terms:
                term_doc_counts[term] = term_doc_counts.get(term, 0) + 1

        avgdl = sum(doc_lengths) / N if N > 0 else 1.0

        # 3. Calculate Smoothed IDF for query terms
        idf: dict[str, float] = {}
        for q_term in set(query_tokens):
            n_q = term_doc_counts.get(q_term, 0)
            # Smoothed IDF: ln( (N - n(q) + 0.5) / (n(q) + 0.5) + 1 )
            idf[q_term] = math.log(((N - n_q + 0.5) / (n_q + 0.5)) + 1.0)

        # 4. Score each chunk
        scored_chunks: list[Chunk] = []

        for i, chunk in enumerate(chunks):
            body_text = chunk_scoring_texts[i]
            c_tokens = chunk_tokens_list[i]
            d_len = doc_lengths[i]

            # Compute term frequency in chunk
            tf: dict[str, int] = {}
            for t in c_tokens:
                tf[t] = tf.get(t, 0) + 1

            # --- BM25 Okapi Core ---
            bm25_score = 0.0
            len_norm = 1.0 - self.b + self.b * (d_len / avgdl if avgdl > 0 else 1.0)

            for q_term in query_tokens:
                f_qd = tf.get(q_term, 0)
                if f_qd > 0:
                    numerator = f_qd * (self.k1 + 1.0)
                    denominator = f_qd + self.k1 * len_norm
                    bm25_score += idf.get(q_term, 0.0) * (numerator / denominator)

            # --- Boilerplate Penalty: -5.0 pts ---
            # Check both body_text and chunk.content for boilerplate
            boilerplate_penalty = 0.0
            is_boilerplate = False
            for bp_re in BOILERPLATE_REGEXES:
                if bp_re.search(body_text) or bp_re.search(chunk.content):
                    boilerplate_penalty = 5.0
                    is_boilerplate = True
                    break

            # --- Financial Salience Boosting (FSB) ---
            salience_boost = 0.0
            boost_reasons: list[str] = []

            # If chunk is boilerplate, do not grant salience boosts
            if not is_boilerplate:
                # 1. Exact ticker match in query: +3.0 pts
                if target_tickers:
                    for ticker in target_tickers:
                        # Look for exact word boundary ticker in actual body text
                        if re.search(r"\b" + re.escape(ticker) + r"\b", body_text):
                            salience_boost += 3.0
                            boost_reasons.append(f"ticker:{ticker}")
                            break

                # 2. Fiscal period match: +2.5 pts
                chunk_periods = set(extract_periods_from_text(body_text))
                period_intersection = query_periods.intersection(chunk_periods)
                if period_intersection:
                    salience_boost += 2.5
                    boost_reasons.append(f"period:{','.join(period_intersection)}")
                elif chunk_periods and ("báo cáo" in query.lower() or "kết quả" in query.lower() or "quý" in query.lower()):
                    # General financial report query matching documented quarters
                    salience_boost += 1.5
                    boost_reasons.append("period_general")

                # 3. Quantitative metric density (>= 2 measurements): +2.0 pts
                metric_matches = _METRIC_PATTERN.findall(body_text)
                if len(metric_matches) >= 2:
                    salience_boost += 2.0
                    boost_reasons.append(f"metrics:{len(metric_matches)}")

                # 4. Audited financial table bonus: +1.5 pts
                if chunk.is_table or "|---" in body_text or "|:---" in body_text:
                    salience_boost += 1.5
                    boost_reasons.append("table")

            # Final Score calculation
            final_score = bm25_score + salience_boost - boilerplate_penalty

            if final_score <= 0.0:
                final_score = 0.0

            chunk.score = round(final_score, 4)
            chunk.metadata["bm25_score"] = round(bm25_score, 4)
            chunk.metadata["salience_boost"] = round(salience_boost, 4)
            chunk.metadata["boost_reasons"] = boost_reasons
            chunk.metadata["boilerplate_penalty"] = boilerplate_penalty

            if discard_non_positive and chunk.score <= 0.0:
                continue

            scored_chunks.append(chunk)

        return scored_chunks
