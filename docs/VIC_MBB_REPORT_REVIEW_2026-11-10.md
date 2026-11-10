# VIC / MBB report review - 2026-11-10

## Scope and evidence

This is an audit of the supplied PDF contents and their local generation receipts. It does not validate the financial figures against issuer filings or give an investment recommendation. The originals were freshly extracted with pypdf; page 1 of each was freshly rendered with Poppler and inspected. Text was extracted from all 31 MBB pages and all 7 VIC pages. The complete VIC text and selected MBB sections were read; other MBB pages were inspected through extracted text summaries. Existing `tmp/pdf-review-20261110` files were not treated as provenance.

| Original | Size / SHA-256 | Metadata |
| --- | --- | --- |
| `D:/Vibe-Trading/output/pdf/VIBE_Research_MBB_20261108.pdf` | 2,147,529 bytes; `48aba4fd40b7b0c0650cf6471de888a4628562a563ddd7f1acc410e89d69941c` | 31 pages; Creator Writer; Producer LibreOffice 26.8.2.2; created 2026-11-08 14:48:20 +07:00 |
| `C:/Users/KIMPC/Downloads/VIC_Vingroup_BaoCao_PhanTich_20261109.pdf` | 67,485 bytes; `f28ab883c1af20ed4dfeaa4e278c8a33971ec499bd5026124f7fdb21a5c6b7c8` | 7 pages; anonymous author; Producer ReportLab; created 2026-11-09 12:08:39 +07:00 |

## Presentation difference

- MBB p1 has the Vibe-Trading brand, report date, explicit unrated status, target-price placeholders, horizon, sourced KPI cards, executive summary and asset facts. Continuing pages have consistent headers, footer and page numbering; charts and claim-level source links are embedded. There are 942 PDF link annotations, including repeated links; that count does not establish source quality.
- VIC p1 is a generic single-column document with no equivalent cover, KPI hierarchy, explicit rating field, page numbers or brand. Literal `---` separators remain visible. Its technical indicator table splits across pp1-2. The PDF contains no image objects and no link annotations; its S1-S11 source list on p7 has titles and dates but no URLs or claim-level source mapping.
- Reuse the institutional renderer and its tables, charts, citations and disclosure fields. A longer page count or a label saying "CFA" does not establish analytical quality or CFA Institute approval.

## Analytical discrepancies and required corrections

The arithmetic below uses values printed in the PDFs solely to test internal consistency. It does not establish those inputs as verified market or financial data.

| Location | Finding | Required treatment |
| --- | --- | --- |
| VIC pp1-2, p6 | The header dates a quote to 11:29 on 09/11/2026, while the narrative calls 228,000 VND the close. Partial-session volume is compared with full-session average volume and then used to infer weak participation. P6 acknowledges that the session was incomplete. | Preserve quote timestamp and session status consistently. Use the last completed candle for closing-price and daily-volume comparisons; do not infer full-session participation from partial volume alone. |
| VIC p3 | CFO 69,245 minus CAPEX 74,505 equals -5,260 billion VND, but FCF is stated as -96,030 without a bridge or alternate definition. | Reconcile period, sign and FCF definition against the original cash-flow statement; disclose excluded investing items. Withhold the FCF-based financing conclusion until reconciled. |
| VIC p4 | Net debt 337,297 divided by total assets about 1,620,000 equals about 20.8%, versus the printed 24.1%. | Recompute using the same date and denominator; show the formula and source inputs. |
| VIC pp3-5 | 2025 cash-flow/leverage/EV-EBITDA metrics, 30/09/2026 balance data and an intraday November quote are discussed together without a reconciled valuation bridge. | Align valuation date, trailing/forecast period, share count, minority interests and cash/debt. Identify unavailable items explicitly. |
| VIC p5 | EPS scenarios, P/E ranges and implied book value are presented with little input provenance. RNAV is correctly described as unavailable; broad sector averages do not replace holding-company valuation. | For a conglomerate, provide sourced segment/SOTP or RNAV inputs, ownership stakes, parent debt, minority interests and overlap controls when available. Otherwise retain an unrated draft and explain what is missing rather than invent a target. |
| VIC p6 | Sales bookings 219,600 and deposits/cooperation capital over 402,000 are combined into "revenue waiting" and used to support a future EPS range. These categories may overlap and deposits/cooperation funding need not equal unrecognized sales. | Do not add them without a documented reconciliation. Separate bookings, backlog, advances, cooperation funding, revenue recognition, ownership share and margin assumptions. |
| VIC pp1-7 | Claims such as all quarterly profit coming from real estate, best-quality segment earnings, a sustainable property margin range, or future EPS lack a complete profit/cash-flow bridge and claim-level evidence. The report itself says the original statements and a true peer comparison are missing. | Distinguish reported facts, calculations, assumptions and inference. Add a segment earnings bridge, cash conversion, related-party exposure, maturity/refinancing analysis and bear/base/bull drivers only where evidence supports them. |
| MBB p2 | The printed assets/equity formula is 1,837,857 / 164,142, approximately 11.2x, but its KPI states 17.7x. | Reuse its visual format, not unchecked numerical content. Recompute derived metrics. |
| MBB pp1,5,11 | P1 gives provisions/pre-provision profit of 33.7%; p5 says the current quarter already exceeds a 40% warning threshold. The printed inputs 5,241 / 15,571 equal 33.66%. | Resolve threshold narratives against computed values and keep signed expense comparisons unambiguous. |
| MBB pp6,25-26,31 | MBB also lacks original statements and key bank ratios and remains an unapproved, unrated draft. Its headings include CFA language, while p26 explicitly states there is no CFA compliance declaration. | Treat MBB as a presentation reference with known evidence limitations, not a certified analytical benchmark. |

## Locally traced cause

The matching session is `C:/Users/KIMPC/.vibe-trading/sessions/724d1a8bcf4b/trace.jsonl`; the original run is `C:/Users/KIMPC/.vibe-trading/runs/20261109_114725_29_448dfd`.

1. The financial-statement tools failed with `Configure exactly one financial_statements source for this symbol in Data Bridge` (trace lines 16, 20, 33 and 107). Some web reads failed HTTP 403; a peer-data request failed the symbol identity lock (line 101).
2. `export_research_report` failed schema validation at lines 122, 127, 130 and 133: missing thesis/risk `body`, invalid price basis, derived bars requiring a formula chart, and missing derivation methods. A repeated-failure guard skipped another call at line 136.
3. At lines 137-138, the assistant used generic `write_file` to create the PDF. Its 67,485-byte receipt and report ID match the supplied file. This path explains the generic ReportLab layout and bypassed the structured renderer's validation, rather than demonstrating a successful institutional export.
4. Subsequent structured exports also failed schema/evidence checks, including source-URL/content mismatches for S2, S3 and S4 (lines 140-152). There is no successful structured export in this original sequence.
5. `C:/Users/KIMPC/.vibe-trading/report_jobs/fdfc31f34c2e47adbfb2f2149a43a02a.json` records the matching SHA-256, `formats: ["pdf"]`, `publication_status: "draft_unverified"` and empty warnings. There is no matching DOCX in that artifact receipt. A generic export's empty warning list must not imply completed financial validation.

## Why the report got thinner on every retry (mechanism)

Reading the trace payload by payload (`agent/tests/fixtures/export_stall_payloads.json`) shows the accepted report went 8 `analysis_sections` -> 3 -> 4. The repair loop was rewarding deletion:

1. **A URL mismatch was reported twice.** `evidence.py` raised one `sources.N.url` issue and then, because the source id was no longer bound, one "Nguồn S1 chưa được công cụ thu thập" issue *per referencing field*. The model cleared the second class by deleting the content that cited the source. The collected page is now bound by id, so a wrong URL is one repairable field and the citing content stays valid.
2. **The repair hint invited deletion.** `_REPAIR_HINTS["EVIDENCE_VALIDATION_FAILED"]` said "bỏ hẳn mục đó". It now says to repair the number or the source binding and to keep `analysis_sections`.
3. **Schema errors surfaced one class per retry.** `_structured_validation_errors` took the first 12 raw errors, so nine near-identical `*.body` errors hid the `price_basis` and `methodology` failures. Errors are now grouped by collapsed field pattern (every list index collapses), counted, and capped at 24 groups.
4. **A `(root)` validator error named no field.** `Thiếu phương pháp/giả định: investment_theses.3` is now parsed into `investment_theses.3`.
5. **The repair packet had no source list.** The model was told "URL không khớp" and invented a replacement. `collected_sources` now lists the pages this run actually read, and `expected_url` names the collected URL.
6. **A peer fetch failed with no resolver hint.** `identity.py` returned only the generic identity error for `VHM.VN`/`VRE.VN`; it now names `search_symbol('VHM.VN')` as the call that authorizes a peer.
7. **A blocked page looked retryable.** `read_url` returned a bare HTTP status; it now returns `error_code` plus a `remedy` naming the issuer IR page, exchange filing or `read_document`.
8. **An empty analysis rendered as a valid document.** The renderer produces eight chapters with no analysis, so the export now carries a structural warning when `analysis_sections` is missing or a section has no paragraphs, bullets or charts.
9. **A heading numbered by the model rendered twice.** The renderer adds its own chapter number, so `1. Kết luận` became `06 1. Kết luận`; the normalizer strips a numbering prefix (a year such as `2026 - Triển vọng` is content and is kept).

## Completion and re-verification requirements

- Keep financial research on `export_research_report`; schema/evidence failures must return actionable feedback and the collected draft, not fall through to generic PDF generation. Validate repaired payloads with tests covering the actual failed shapes.
- Reuse existing report components for layout, citations, statement scope/date/unit fields, assumptions, disclosures and draft status. Do not promote evidence or publication status through model-authored claims.
- Before regenerating an actionable VIC analysis, obtain and read the original consolidated statements/notes, reconcile the contradictions above, and retain original-source receipts and claim mappings. Without them, a re-export can only be a clearly limited draft with unsupported conclusions removed.
- A regenerated artifact needs text and page-image review, working citations, consistent pagination/tables, and PDF/DOCX parity when both are promised. Provider-backed financial acceptance and packaged desktop acceptance are separate from local unit/build checks.

No original PDF or runtime report state was modified. No issuer filing, live price, CFA compliance, live provider call or packaged-desktop behavior was independently verified in this audit.

## Local implementation checks

- Confirmed the equity-export routing guard preserves existing files and prevents generic PDF fallback after failed structured export. Reconciled report instructions with supported ratings, source requirements, sector-specific valuation and explicit unavailable inputs; removed the renderer's unsupported CFA running-header badge.
- Aligned the API and frontend's implicit page minimum with the export tool/service default of one page. An explicitly requested minimum remains enforced; this default does not define sufficient research depth.
- Backend focused validation: 118 unique tests passed across report routing, renderer, normalization, evidence, valuation, depth, preview API and file-path boundaries. Frontend API/report-engine validation: 26 tests passed.
- Frontend preview/store tests passed 36 cases, layout/navigation/banner tests passed 23 cases, and the final TypeScript/Vite production build passed after the mobile-sidebar correction.
- Mechanism fixes above are covered by `agent/tests/test_report_repair_keeps_analysis.py` (13 cases): URL mismatch stays one repairable field, the accepted report keeps its analysis across a rejection, the repair hints forbid deletion, schema errors group repeated indices and name every class in one response, a `(root)` message resolves to its payload field, `collected_sources` lists what the run read, a peer mismatch names `search_symbol(...)`, and a numbered heading is stripped while a year is kept.
- Focused report/evidence group after these fixes: 90 tests passed. Full backend suite: 21825 passed, 222 skipped, 7 failed. All 7 failures reproduce on the unmodified tree (MCP manifest tool counts, MCP skill inventory, qveris MCP registration, provider reasoning-effort record, locale packaged version, two playbook-surface listings) and are unrelated to this work.
- Frontend full suite: 128 files / 1167 tests passed; `npm run build` passed.
- Browser smoke used mocked API/source responses and an existing MBB page, without modifying or validating that page's figures. Shared file/source tabs, pointer resizing, PDF page retention, Escape cleanup and responsive bounds passed at viewport widths 1491, 1024, 768, 390 and 320 px. Desktop chat and preview share an edge; mobile sidebar is 48 px. Review images are `artifacts/ui-review/shared-preview-tabs-desktop.png` and `artifacts/ui-review/shared-preview-tabs-mobile.png`.
- A hidden Electron smoke using a local source fixture confirmed native-view suspension during pointer drag, restoration of the same web contents and history afterward, zero gap between chat and preview, overlay cleanup on tab switches, last-URL restoration and close cleanup. This is a development-runtime check, not installed-package acceptance. Electron TypeScript build passed.
- These changes do not regenerate the supplied VIC PDF, establish CFA compliance or guarantee every model-written formula in narrative prose. Original statements and reconciliation are still required for a verified VIC report.
