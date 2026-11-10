import { useReportPreviewStore } from "@/stores/reportPreview";
import type { ReportEngineJob } from "@/lib/reportEngine";
import { REPORT_MEDIA_TYPES } from "@/lib/reportEngine";

function receipt(jobId = "a".repeat(32)): ReportEngineJob {
  return {
    job_id: jobId,
    status: "succeeded",
    formats: ["docx", "pdf"],
    artifacts: [
      {
        report_id: "b".repeat(32),
        filename: "research.docx",
        media_type: REPORT_MEDIA_TYPES.docx,
        download_url: `/api/reports/${"b".repeat(32)}`,
        sha256: "c".repeat(64),
        size_bytes: 1000,
      },
    ],
    error: null,
    publication_status: "draft_unverified",
    created_at: "2026-11-07T00:00:00Z",
    updated_at: "2026-11-07T00:00:01Z",
  };
}

beforeEach(() => {
  useReportPreviewStore.getState().close();
});

it("opens a source without dropping the document that was already open", () => {
  const store = useReportPreviewStore.getState();
  store.openArtifact("b".repeat(32));
  store.openSource("https://example.com/report", "Báo cáo");

  const state = useReportPreviewStore.getState();
  expect(state.tabs).toHaveLength(2);
  expect(state.activeId).toBe(state.tabs[1].id);
  expect(state.tabs[0].selection).toEqual({ kind: "report", reportId: "b".repeat(32) });
  expect(state.tabs[1].selection).toEqual({ kind: "source", sourceUrl: "https://example.com/report", title: "Báo cáo" });
});

it("treats reopening the same preview as a switch, not a second tab", () => {
  const store = useReportPreviewStore.getState();
  store.openSource("https://example.com/report", "Báo cáo");
  store.openArtifact("b".repeat(32));
  store.openSource("https://example.com/report", "Báo cáo");

  const state = useReportPreviewStore.getState();
  expect(state.tabs).toHaveLength(2);
  expect(state.activeId).toBe(state.tabs[0].id);
});

it("closes one tab and hands focus to a neighbour", () => {
  const store = useReportPreviewStore.getState();
  store.openSource("https://example.com/a", "A");
  store.openSource("https://example.com/b", "B");
  store.openSource("https://example.com/c", "C");

  const state = useReportPreviewStore.getState();
  expect(state.tabs).toHaveLength(3);
  const middleId = state.tabs[1].id;

  useReportPreviewStore.getState().closeTab(middleId);
  const after = useReportPreviewStore.getState();
  expect(after.tabs).toHaveLength(2);
  expect(after.tabs.some((tab) => tab.id === middleId)).toBe(false);
  // The active tab was the third one, so closing the middle one must not
  // change what is showing.
  expect(after.activeId).toBe(after.tabs[1].id);
});

it("moves focus to the neighbouring tab when the active one is closed", () => {
  const store = useReportPreviewStore.getState();
  store.openSource("https://example.com/a", "A");
  store.openSource("https://example.com/b", "B");
  store.openSource("https://example.com/c", "C");

  const before = useReportPreviewStore.getState();
  const activeId = before.activeId!;
  useReportPreviewStore.getState().closeTab(activeId);

  const after = useReportPreviewStore.getState();
  expect(after.tabs).toHaveLength(2);
  expect(after.activeId).not.toBeNull();
  expect(after.tabs.some((tab) => tab.id === after.activeId)).toBe(true);
});

it("clears every tab when the pane closes outright", () => {
  const store = useReportPreviewStore.getState();
  store.openJob(receipt());
  store.openSource("https://example.com/report", "Báo cáo");
  expect(useReportPreviewStore.getState().tabs).toHaveLength(2);

  useReportPreviewStore.getState().close();
  const state = useReportPreviewStore.getState();
  expect(state.tabs).toHaveLength(0);
  expect(state.activeId).toBeNull();
});

it("rejects a source URL that is not safe to render", () => {
  useReportPreviewStore.getState().openSource("javascript:alert(1)");
  expect(useReportPreviewStore.getState().tabs).toHaveLength(0);
});

it("opens an AI-search result as its own tab", () => {
  useReportPreviewStore.getState().openResearch({
    query: "VIC HOSE",
    summary_markdown: "Kết quả",
    sources: [{ title: "Nguồn", url: "https://example.com/a" }],
  });

  const state = useReportPreviewStore.getState();
  expect(state.tabs).toHaveLength(1);
  expect(state.tabs[0].kind).toBe("research");
  expect(state.tabs[0].title).toContain("VIC HOSE");
});
