# BRIEFING — 2026-11-08T14:55:00Z

## Mission
Xây dựng và kiểm thử toàn diện module Extractor (DOM Cleaning 3-stage, GFM Markdown Converter cho bảng tài chính, 3-tier Deduplicator) trong `agent/src/tools/extractor/`.

## 🔒 My Identity
- Archetype: teamwork_worker
- Roles: implementer, qa, specialist
- Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m2_dom_cleaner_1
- Original parent: fc6481d3-86d0-438b-b509-e00be11b4dba
- Milestone: M2 (DOM Cleaning, High-Fidelity Markdown & Deduplication)

## 🔒 Key Constraints
- Tôn trọng triệt để Mandatory Integrity Warning: Không hardcode kết quả, không viết dummy/facade, mọi triển khai phải chuẩn xác thực chất.
- Tuân thủ nguyên tắc không icon/emoji, phản hồi tiếng Việt chuẩn mực kỹ thuật theo rule của chủ tịch.
- Độc quyền sở hữu các file:
  * `agent/src/tools/extractor/dom_cleaner.py`
  * `agent/src/tools/extractor/markdown_converter.py`
  * `agent/src/tools/extractor/deduplicator.py`
  * `agent/src/tools/extractor/__init__.py`
- Kiểm thử và xác thực với `.venv\Scripts\python`.

## Current Parent
- Conversation ID: fc6481d3-86d0-438b-b509-e00be11b4dba
- Updated: 2026-11-08T14:55:00Z

## Task Summary
- **What to build**: 
  1. `dom_cleaner.py`: 3-stage DOM cleaning pipeline (`lxml.html` fast parsing, boilerplate stripping, text-to-tag / link density scoring, Rust `nh3` whitelist sanitization).
  2. `markdown_converter.py`: High-fidelity GFM Table & Markdown conversion engine (numeric/percentage right-aligned, text left-aligned, colspan/rowspan handling, Vietnamese currency/date preservation, metadata extraction).
  3. `deduplicator.py`: 3-tier cross-site deduplication (Canonical URL, SHA-256 exact text hash, 64-bit SimHash with Vietnamese stop words & 3-grams, syndication source aggregation).
  4. `__init__.py`: CleanDocument dataclass/model, `clean_html(html_str, url)`, `deduplicate_documents(docs)`.
- **Success criteria**: All modules import cleanly, tests pass with realistic Vietnamese financial HTML fixtures, CleanDocument interface adheres to M2->M3 contract.
- **Interface contracts**: `CleanDocument`: `url: str, canonical_url: str, title: str, clean_markdown: str, metadata: dict, syndicated_sources: list[str], simhash: int`
- **Code layout**: `agent/src/tools/extractor/`

## Change Tracker
- **Files modified**: None yet
- **Build status**: Initializing
- **Pending issues**: None

## Quality Status
- **Build/test result**: Untested
- **Lint status**: Clean
- **Tests added/modified**: Pending

## Key Decisions Made
- Sử dụng `lxml.html` cho Stage 1 & 2 để đạt hiệu năng <3ms và selector CSS mạnh mẽ.
- Sử dụng `nh3` cho Stage 3 để sanitize chuẩn Rust, giữ whitelist tag an toàn.
- Thiết kế SimHash 64-bit tự sinh hoặc tối ưu toán tử bit với sha256 rolling window, không cần thư viện ngoài phức tạp nếu đã có hashlib.
- Hỗ trợ parser bảng HTML phức tạp với colspan/rowspan chuyển thành ô GFM tương ứng.

## Artifact Index
- `d:\Vibe-Trading\.agents\teamwork\worker_m2_dom_cleaner_1\DISPATCH.md` — Task assignment
- `d:\Vibe-Trading\.agents\teamwork\worker_m2_dom_cleaner_1\progress.md` — Progress heartbeat
- `d:\Vibe-Trading\.agents\teamwork\worker_m2_dom_cleaner_1\handoff.md` — Final handoff report
