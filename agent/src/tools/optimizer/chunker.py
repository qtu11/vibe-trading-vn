"""Structural and Semantic Document Chunker for Financial Text.

Decomposes Markdown documents along hierarchical structural boundaries (H1-H4),
preserves atomic financial tables (replicating table headers across sub-chunks),
splits sentences on natural grammatical boundaries without breaking numbers,
tickers, or abbreviations, and applies a sliding window with 15% overlap.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional
from pydantic import BaseModel, Field


def count_tokens(text: str) -> int:
    """Estimate token count for Vietnamese and English financial text (~4 chars/token)."""
    if not text:
        return 0
    # Heuristic consistent with agent/src/agent/context_budget.py (~4 chars per token)
    return max(1, len(text) // 4)


class Chunk(BaseModel):
    """Represents a structural/semantic chunk of a document."""

    index: int = Field(description="Sequential position of chunk in original document")
    content: str = Field(description="Clean text content of the chunk with breadcrumb header")
    raw_content: str = Field(default="", description="Text content without breadcrumb prefix")
    breadcrumb: str = Field(default="", description="Section hierarchy breadcrumb [Section: H1 > H2]")
    token_count: int = Field(default=0, description="Estimated token count")
    score: float = Field(default=0.0, description="BM25-FSB salience score")
    is_table: bool = Field(default=False, description="Whether this chunk is or contains an atomic table")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional chunk attributes")


# Protected abbreviations in Vietnamese & English financial / administrative texts
_COMMON_ABBREVIATIONS: tuple[str, ...] = (
    "TP", "Tp", "TX", "TT", "CP", "NĐ", "QĐ", "TTg", "TAND", "VKSND",
    "Co", "Ltd", "Inc", "Corp", "LLC", "JSC", "PLC", "Bros",
    "St", "Mr", "Mrs", "Ms", "Dr", "Prof", "TS", "ThS", "PGS", "GS",
    "vs", "eg", "ie", "etc", "vol", "no", "approx", "est",
    "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

_ABBR_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(abbr) for abbr in _COMMON_ABBREVIATIONS) + r")\.",
    re.IGNORECASE,
)

# Sentence boundary regex adhering to specification: (?<=[.!?])\s+(?=[A-ZÀ-Ỹ0-9])
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ỹ0-9])")
_PLACEHOLDER_DOT = "\u2024"  # One-dot leader (U+2024) to protect abbreviation dots


def split_sentences(text: str) -> list[str]:
    """Split text into sentences along natural grammatical boundaries.

    Guarantees:
    - Does NOT split decimals and percentages (15.4%, 3.5 tỷ, 1.234,5)
    - Does NOT split abbreviations (TP. HCM, Co., Ltd., Dr. Smith)
    - Does NOT split ticker symbols or currency pairs (USD/VND)
    """
    cleaned = text.strip()
    if not cleaned:
        return []

    # Step 1: Protect known abbreviations
    def _mask_abbr(m: re.Match[str]) -> str:
        return m.group(1) + _PLACEHOLDER_DOT

    masked = _ABBR_PATTERN.sub(_mask_abbr, cleaned)

    # Protect single-capital initial patterns like "A. B. Smith"
    masked = re.sub(r"\b([A-ZÀ-Ỹ])\.\s+(?=[A-ZÀ-Ỹ])", r"\1" + _PLACEHOLDER_DOT + " ", masked)

    # Step 2: Split using natural language boundary regex
    raw_sentences = _SENTENCE_BOUNDARY_RE.split(masked)

    # Step 3: Unmask and strip sentences
    sentences: list[str] = []
    for s in raw_sentences:
        restored = s.replace(_PLACEHOLDER_DOT, ".").strip()
        if restored:
            sentences.append(restored)

    return sentences


class SemanticChunker:
    """Hierarchical structural & semantic chunker.

    Splits on H1-H4 Markdown headings, retains section breadcrumbs, preserves
    tables and code blocks atomically, and forms chunks of target size with sliding
    window overlap.
    """

    def __init__(
        self,
        target_chunk_tokens: int = 350,
        min_chunk_tokens: int = 300,
        max_chunk_tokens: int = 400,
        overlap_tokens: int = 50,
    ) -> None:
        self.target_chunk_tokens = target_chunk_tokens
        self.min_chunk_tokens = min_chunk_tokens
        self.max_chunk_tokens = max_chunk_tokens
        self.overlap_tokens = overlap_tokens

    def chunk(self, markdown_text: str, source_title: str = "") -> list[Chunk]:
        """Split a Markdown document into structured semantic chunks."""
        if not markdown_text or not markdown_text.strip():
            return []

        # 1. Parse into hierarchical sections
        sections = self._parse_sections(markdown_text, source_title)

        # 2. Within each section, chunk paragraphs, tables, and blocks
        chunks: list[Chunk] = []
        chunk_idx = 0

        for section in sections:
            breadcrumb = section["breadcrumb"]
            blocks = section["blocks"]

            for block in blocks:
                block_type = block["type"]
                block_content = block["content"].strip()
                if not block_content:
                    continue

                if block_type == "table":
                    # Atomic financial table chunking
                    table_chunks = self._chunk_table(
                        block_content,
                        breadcrumb=breadcrumb,
                        start_idx=chunk_idx,
                    )
                    chunks.extend(table_chunks)
                    chunk_idx += len(table_chunks)

                elif block_type == "code":
                    # Atomic code block
                    tok_count = count_tokens(block_content)
                    full_content = f"{breadcrumb}\n\n{block_content}" if breadcrumb else block_content
                    chunks.append(
                        Chunk(
                            index=chunk_idx,
                            content=full_content,
                            raw_content=block_content,
                            breadcrumb=breadcrumb,
                            token_count=tok_count,
                            is_table=False,
                            metadata={"type": "code"},
                        )
                    )
                    chunk_idx += 1

                elif block_type == "quote":
                    # Blockquote chunking
                    tok_count = count_tokens(block_content)
                    if tok_count <= self.max_chunk_tokens:
                        full_content = f"{breadcrumb}\n\n{block_content}" if breadcrumb else block_content
                        chunks.append(
                            Chunk(
                                index=chunk_idx,
                                content=full_content,
                                raw_content=block_content,
                                breadcrumb=breadcrumb,
                                token_count=tok_count,
                                is_table=False,
                                metadata={"type": "quote"},
                            )
                        )
                        chunk_idx += 1
                    else:
                        text_chunks = self._chunk_text(
                            block_content,
                            breadcrumb=breadcrumb,
                            start_idx=chunk_idx,
                        )
                        chunks.extend(text_chunks)
                        chunk_idx += len(text_chunks)

                else:
                    # Regular text / paragraphs
                    text_chunks = self._chunk_text(
                        block_content,
                        breadcrumb=breadcrumb,
                        start_idx=chunk_idx,
                    )
                    chunks.extend(text_chunks)
                    chunk_idx += len(text_chunks)

        return chunks

    def _parse_sections(self, markdown_text: str, default_title: str) -> list[dict[str, Any]]:
        """Parse markdown into sections based on H1-H4 headings."""
        lines = markdown_text.splitlines()
        sections: list[dict[str, Any]] = []

        heading_stack: list[str] = [default_title] if default_title else []
        current_blocks: list[dict[str, Any]] = []
        current_lines: list[str] = []
        in_code_block = False
        in_table = False

        heading_re = re.compile(r"^(#{1,4})\s+(.+)$")

        def flush_text_lines():
            nonlocal current_lines
            if current_lines:
                text_body = "\n".join(current_lines).strip()
                if text_body:
                    current_blocks.append({"type": "text", "content": text_body})
                current_lines = []

        def flush_table_lines():
            nonlocal current_lines, in_table
            if current_lines:
                table_body = "\n".join(current_lines).strip()
                if table_body:
                    current_blocks.append({"type": "table", "content": table_body})
                current_lines = []
            in_table = False

        def flush_code_lines():
            nonlocal current_lines, in_code_block
            if current_lines:
                code_body = "\n".join(current_lines).strip()
                if code_body:
                    current_blocks.append({"type": "code", "content": code_body})
                current_lines = []
            in_code_block = False

        def get_breadcrumb() -> str:
            if not heading_stack:
                return "[Section: General]"
            return f"[Section: {' > '.join(heading_stack)}]"

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Handle code blocks
            if stripped.startswith("```"):
                if in_code_block:
                    current_lines.append(line)
                    flush_code_lines()
                else:
                    if in_table:
                        flush_table_lines()
                    else:
                        flush_text_lines()
                    in_code_block = True
                    current_lines.append(line)
                i += 1
                continue

            if in_code_block:
                current_lines.append(line)
                i += 1
                continue

            # Check for Markdown table lines
            is_table_line = stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2
            if is_table_line:
                if not in_table:
                    flush_text_lines()
                    in_table = True
                current_lines.append(line)
                i += 1
                continue
            elif in_table:
                # Table ended
                flush_table_lines()

            # Check for H1-H4 headings
            hmatch = heading_re.match(stripped)
            if hmatch:
                flush_text_lines()
                # Save previous section if it had blocks
                if current_blocks:
                    sections.append({
                        "breadcrumb": get_breadcrumb(),
                        "blocks": current_blocks,
                    })
                    current_blocks = []

                level = len(hmatch.group(1))
                heading_text = hmatch.group(2).strip()

                # Adjust heading stack according to hierarchy level
                # Level 1 clears down to level 1, etc.
                if default_title and heading_stack and heading_stack[0] == default_title:
                    # Keep default title at root
                    heading_stack = [default_title] + heading_stack[1:level]
                else:
                    heading_stack = heading_stack[: level - 1]

                heading_stack.append(heading_text)
                i += 1
                continue

            # Check for blockquotes
            if stripped.startswith(">"):
                quote_lines = [line]
                while i + 1 < len(lines) and lines[i + 1].strip().startswith(">"):
                    i += 1
                    quote_lines.append(lines[i])
                flush_text_lines()
                current_blocks.append({"type": "quote", "content": "\n".join(quote_lines)})
                i += 1
                continue

            # Regular text line
            current_lines.append(line)
            i += 1

        # End of lines: flush remaining
        if in_code_block:
            flush_code_lines()
        elif in_table:
            flush_table_lines()
        else:
            flush_text_lines()

        if current_blocks:
            sections.append({
                "breadcrumb": get_breadcrumb(),
                "blocks": current_blocks,
            })

        if not sections:
            # Fallback for plain text without headings
            sections.append({
                "breadcrumb": get_breadcrumb(),
                "blocks": [{"type": "text", "content": markdown_text.strip()}],
            })

        return sections

    def _chunk_table(self, table_text: str, breadcrumb: str, start_idx: int) -> list[Chunk]:
        """Preserve table atomically or replicate header row across sub-chunks if oversized."""
        lines = [line.strip() for line in table_text.splitlines() if line.strip()]
        if len(lines) < 2:
            tok = count_tokens(table_text)
            full_content = f"{breadcrumb}\n\n{table_text}" if breadcrumb else table_text
            return [
                Chunk(
                    index=start_idx,
                    content=full_content,
                    raw_content=table_text,
                    breadcrumb=breadcrumb,
                    token_count=tok,
                    is_table=True,
                    metadata={"type": "table", "rows": len(lines)},
                )
            ]

        # Check full table token count
        total_tok = count_tokens(table_text)
        if total_tok <= self.max_chunk_tokens:
            full_content = f"{breadcrumb}\n\n{table_text}" if breadcrumb else table_text
            return [
                Chunk(
                    index=start_idx,
                    content=full_content,
                    raw_content=table_text,
                    breadcrumb=breadcrumb,
                    token_count=total_tok,
                    is_table=True,
                    metadata={"type": "table", "rows": len(lines)},
                )
            ]

        # Table exceeds max_chunk_tokens: split rows with header replication
        header_row = lines[0]
        delimiter_row = lines[1]
        data_rows = lines[2:]

        table_header = f"{header_row}\n{delimiter_row}"
        header_tok = count_tokens(table_header)

        chunks: list[Chunk] = []
        cur_rows: list[str] = []
        cur_tok = header_tok
        sub_idx = start_idx

        for row in data_rows:
            row_tok = count_tokens(row)
            if cur_tok + row_tok > self.max_chunk_tokens and cur_rows:
                # Flush current table partition
                partition_text = table_header + "\n" + "\n".join(cur_rows)
                full_content = f"{breadcrumb}\n\n{partition_text}" if breadcrumb else partition_text
                chunks.append(
                    Chunk(
                        index=sub_idx,
                        content=full_content,
                        raw_content=partition_text,
                        breadcrumb=breadcrumb,
                        token_count=count_tokens(partition_text),
                        is_table=True,
                        metadata={"type": "table_partition", "rows": len(cur_rows)},
                    )
                )
                sub_idx += 1
                cur_rows = [row]
                cur_tok = header_tok + row_tok
            else:
                cur_rows.append(row)
                cur_tok += row_tok

        if cur_rows:
            partition_text = table_header + "\n" + "\n".join(cur_rows)
            full_content = f"{breadcrumb}\n\n{partition_text}" if breadcrumb else partition_text
            chunks.append(
                Chunk(
                    index=sub_idx,
                    content=full_content,
                    raw_content=partition_text,
                    breadcrumb=breadcrumb,
                    token_count=count_tokens(partition_text),
                    is_table=True,
                    metadata={"type": "table_partition", "rows": len(cur_rows)},
                )
            )

        return chunks

    def _chunk_text(self, text: str, breadcrumb: str, start_idx: int) -> list[Chunk]:
        """Split text blocks into sentences with sliding window overlap (target 350 +- 50 tokens)."""
        sentences = split_sentences(text)
        if not sentences:
            return []

        chunks: list[Chunk] = []
        cur_sentences: list[str] = []
        cur_tokens = 0
        sub_idx = start_idx

        i = 0
        while i < len(sentences):
            sentence = sentences[i]
            s_tok = count_tokens(sentence)

            # If a single sentence is larger than max_chunk_tokens, break by clauses
            if s_tok > self.max_chunk_tokens:
                if cur_sentences:
                    chunk_text = " ".join(cur_sentences)
                    full_content = f"{breadcrumb}\n\n{chunk_text}" if breadcrumb else chunk_text
                    chunks.append(
                        Chunk(
                            index=sub_idx,
                            content=full_content,
                            raw_content=chunk_text,
                            breadcrumb=breadcrumb,
                            token_count=count_tokens(chunk_text),
                            is_table=False,
                            metadata={"type": "text"},
                        )
                    )
                    sub_idx += 1
                    cur_sentences = []
                    cur_tokens = 0

                # Fragment long sentence
                parts = re.split(r"(?<=[,;:])\s+", sentence)
                part_accum: list[str] = []
                part_tok = 0
                for part in parts:
                    pt = count_tokens(part)
                    if part_tok + pt > self.target_chunk_tokens and part_accum:
                        p_text = " ".join(part_accum)
                        full_content = f"{breadcrumb}\n\n{p_text}" if breadcrumb else p_text
                        chunks.append(
                            Chunk(
                                index=sub_idx,
                                content=full_content,
                                raw_content=p_text,
                                breadcrumb=breadcrumb,
                                token_count=count_tokens(p_text),
                                is_table=False,
                                metadata={"type": "text_part"},
                            )
                        )
                        sub_idx += 1
                        part_accum = [part]
                        part_tok = pt
                    else:
                        part_accum.append(part)
                        part_tok += pt
                if part_accum:
                    p_text = " ".join(part_accum)
                    full_content = f"{breadcrumb}\n\n{p_text}" if breadcrumb else p_text
                    chunks.append(
                        Chunk(
                            index=sub_idx,
                            content=full_content,
                            raw_content=p_text,
                            breadcrumb=breadcrumb,
                            token_count=count_tokens(p_text),
                            is_table=False,
                            metadata={"type": "text_part"},
                        )
                    )
                    sub_idx += 1
                i += 1
                continue

            # Check if adding this sentence exceeds target/max chunk tokens
            if cur_tokens + s_tok > self.target_chunk_tokens and cur_tokens >= self.min_chunk_tokens:
                # Finalize current chunk
                chunk_text = " ".join(cur_sentences)
                full_content = f"{breadcrumb}\n\n{chunk_text}" if breadcrumb else chunk_text
                chunks.append(
                    Chunk(
                        index=sub_idx,
                        content=full_content,
                        raw_content=chunk_text,
                        breadcrumb=breadcrumb,
                        token_count=count_tokens(chunk_text),
                        is_table=False,
                        metadata={"type": "text"},
                    )
                )
                sub_idx += 1

                # Calculate sliding window overlap (~50 tokens from tail)
                overlap_sentences: list[str] = []
                overlap_accum = 0
                for prev_s in reversed(cur_sentences):
                    ps_tok = count_tokens(prev_s)
                    if overlap_accum + ps_tok <= self.overlap_tokens or not overlap_sentences:
                        overlap_sentences.insert(0, prev_s)
                        overlap_accum += ps_tok
                    else:
                        break

                cur_sentences = overlap_sentences + [sentence]
                cur_tokens = sum(count_tokens(s) for s in cur_sentences)
            else:
                cur_sentences.append(sentence)
                cur_tokens += s_tok

            i += 1

        # Flush final sentences
        if cur_sentences:
            chunk_text = " ".join(cur_sentences)
            full_content = f"{breadcrumb}\n\n{chunk_text}" if breadcrumb else chunk_text
            chunks.append(
                Chunk(
                    index=sub_idx,
                    content=full_content,
                    raw_content=chunk_text,
                    breadcrumb=breadcrumb,
                    token_count=count_tokens(chunk_text),
                    is_table=False,
                    metadata={"type": "text"},
                )
            )

        return chunks
