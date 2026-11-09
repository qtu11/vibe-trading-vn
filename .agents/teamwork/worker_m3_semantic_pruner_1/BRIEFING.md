# BRIEFING — 2026-11-08T14:56:00Z

## Mission
Xây dựng module Semantic Token Optimization & Adaptive Context Pruning (WS3 / M3) bao gồm chunker.py, bm25_scorer.py, budgeter.py và __init__.py, giúp cắt giảm 75-90% token rác, bảo vệ bảng biểu tài chính và tích hợp BM25-FSB.

## 🔒 My Identity
- Archetype: teamwork_worker
- Roles: implementer, qa, specialist
- Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m3_semantic_pruner_1
- Original parent: fc6481d3-86d0-438b-b509-e00be11b4dba
- Milestone: M3 (Semantic Token Optimization & Adaptive Context Pruning)

## 🔒 Key Constraints
- Sở hữu độc quyền và chỉ được tạo/sửa:
  * `agent/src/tools/optimizer/chunker.py`
  * `agent/src/tools/optimizer/bm25_scorer.py`
  * `agent/src/tools/optimizer/budgeter.py`
  * `agent/src/tools/optimizer/__init__.py`
- Tuyệt đối không gian lận (No Cheating): không hardcode kết quả, không tạo facade/dummy logic, duy trì state và hành vi thực tế.
- Tỷ lệ cắt giảm token mục tiêu: 75-90% token rác nhưng không làm rơi bảng tài chính và số liệu định lượng.
- Bảo tồn thứ tự tài liệu gốc (Narrative Order Preservation) khi tổng hợp các chunk được chọn.
- Kiểm thử và xác minh bằng `.venv\Scripts\python`.

## Current Parent
- Conversation ID: fc6481d3-86d0-438b-b509-e00be11b4dba
- Updated: not yet

## Task Summary
- **What to build**:
  1. `chunker.py`: Phân đoạn phân tầng H1-H4, gắn breadcrumbs, bảo toàn khối bảng biểu atomic (nhân bản header nếu phân trang), tách câu tự nhiên bảo vệ số/ticker/viết tắt, cửa sổ trượt gối đầu 15%.
  2. `bm25_scorer.py`: BM25 Okapi thuần Python, tokenizer tài chính song ngữ VN/EN, salience bonus (+ticker, +kỳ báo cáo, +mật độ số liệu, +bảng), boilerplate penalty (-5 điểm).
  3. `budgeter.py`: Phân bổ ngân sách động theo headroom AgentLoop, lọc top-k theo ngưỡng điểm, sắp xếp lại theo original index, gắn metadata nguồn.
  4. `__init__.py`: API chuẩn hóa `prune_document` và `prune_documents`, trả về `PrunedDocument`.
- **Success criteria**: Cắt giảm 75-90% token rác, giữ 100% bảng tài chính và số liệu trọng yếu, test độc lập pass.
- **Interface contracts**: PROJECT.md: `CleanDocument` -> `PrunedDocument`.
- **Code layout**: `agent/src/tools/optimizer/`.

## Key Decisions Made
- Sử dụng regex thuần Python cho tokenizer và sentence boundary để không phụ thuộc vào thư viện bên ngoài nặng, đảm bảo latency < 10ms.
- Phân tách cấu trúc bảng Markdown chính xác: giữ nguyên header và delimiter row khi chia tách bảng quá lớn.
- Khớp nối trực tiếp với các kiểu dữ liệu `CleanDocument` và `PrunedDocument` theo đúng Interface Contract trong PROJECT.md.

## Artifact Index
- `agent/src/tools/optimizer/chunker.py` — Structural & Semantic chunking engine
- `agent/src/tools/optimizer/bm25_scorer.py` — BM25 Okapi + Financial Salience Boosting
- `agent/src/tools/optimizer/budgeter.py` — Adaptive Token Budgeting & narrative order restoration
- `agent/src/tools/optimizer/__init__.py` — Unified interface `prune_document` / `prune_documents`

## Change Tracker
- **Files modified**: Chưa tạo tệp nào
- **Build status**: Pending
- **Pending issues**: Chưa có

## Quality Status
- **Build/test result**: Pending
- **Lint status**: 0 violations
- **Tests added/modified**: Pending

## Loaded Skills
- Không yêu cầu skill bổ sung ngoài chuẩn hệ thống.
