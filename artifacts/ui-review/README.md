# UI verification — 2026-11-07

Screenshots show the real Agent, report card/sidebar, composer model controls and context components in an isolated Vite fixture. API responses and EventSource were intercepted locally; the document, chart and model metadata are explicitly simulated. No provider, trading or live account requests were made.

- `report-sidebar-desktop.png`: 1280×720; canonical PDF page rendered as PNG, with DOCX/PDF/PPTX downloads.
- `report-sidebar-mobile-320.png`: 320×640; report fills the main area and leaves no hidden chat controls in the accessibility tree.
- `report-sidebar-mobile-390.png`: 390×844; complete preview page and export footer.
- `report-card-mobile-320.png`: compact brand header, legible draft/simulation badge.
- `composer-model-mobile-320.png`: model and reasoning popover stays between x=64 and x=304.
- `context-existing-mobile-320.png`: existing-chat metadata; bounded, scrollable popover, no inferred percentage without prompt usage.
- `context-custom-draft-mobile-390.png`: selected custom model appears before the first message; fallback capacity is labelled, automatic compaction state is visible.

The initial native PDF iframe stayed blank in the in-app WebView. The final implementation uses authenticated server-rendered PNG pages from the PDF instead. Escape closes the sidebar and returns keyboard focus to the initiating report button. At 320 and 390 pixels the tested UI had no horizontal overflow.

This verifies component rendering and interaction with controlled responses, not live data correctness or packaged desktop acceptance.
