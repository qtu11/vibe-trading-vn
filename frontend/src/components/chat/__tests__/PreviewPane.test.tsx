import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PreviewPane } from "../PreviewPane";
import { api, fetchReportPreviewPage } from "@/lib/api";
import { REPORT_MEDIA_TYPES, type ReportEngineJob, type ReportFormat } from "@/lib/reportEngine";
import { useReportPreviewStore } from "@/stores/reportPreview";
import type { SourceBrowserState } from "@/desktop";

vi.mock("@/lib/api", () => ({
  api: { getReportJobForArtifact: vi.fn(), getReportPreviewPages: vi.fn() },
  downloadGeneratedReport: vi.fn(),
  fetchReportPreviewPage: vi.fn(),
}));

function receipt(formats: ReportFormat[] = ["docx", "pdf", "pptx"], jobId = "a".repeat(32)): ReportEngineJob {
  return {
    job_id: jobId,
    status: "succeeded",
    formats,
    artifacts: formats.map((format, index) => ({
      report_id: String(index + 1).repeat(32),
      filename: `research.${format}`,
      media_type: REPORT_MEDIA_TYPES[format],
      download_url: `/api/reports/${String(index + 1).repeat(32)}`,
      sha256: "c".repeat(64),
      size_bytes: 1000,
    })),
    error: null,
    publication_status: "draft_unverified",
    created_at: "2026-11-07T00:00:00Z",
    updated_at: "2026-11-07T00:00:01Z",
  };
}

beforeEach(() => {
  localStorage.clear();
  useReportPreviewStore.getState().close();
  vi.mocked(fetchReportPreviewPage).mockReset().mockResolvedValue(new Blob(["png"], { type: "image/png" }));
  vi.mocked(api.getReportJobForArtifact).mockReset().mockResolvedValue(receipt());
  vi.mocked(api.getReportPreviewPages).mockReset().mockResolvedValue(2);
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:report-preview") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
});

afterEach(() => {
  act(() => useReportPreviewStore.getState().close());
  delete window.vibeDesktop;
  vi.unstubAllGlobals();
});

it("opens several previews at once and shows a tab for each", async () => {
  useReportPreviewStore.getState().openArtifact("b".repeat(32));
  useReportPreviewStore.getState().openSource("https://example.com/report", "Nguồn A");
  useReportPreviewStore.getState().openSource("https://example.com/other", "Nguồn B");

  render(<PreviewPane />);

  const tabs = screen.getAllByRole("tab");
  expect(tabs).toHaveLength(3);
  expect(tabs[2]).toHaveAttribute("aria-selected", "true");
  // The active tab's content is showing.
  expect(screen.getByTitle("Nguồn: Nguồn B")).toHaveAttribute("src", "https://example.com/other");
});

it("switches to another tab without closing the one it leaves", async () => {
  useReportPreviewStore.getState().openSource("https://example.com/a", "Nguồn A");
  useReportPreviewStore.getState().openSource("https://example.com/b", "Nguồn B");
  render(<PreviewPane />);

  fireEvent.click(screen.getByRole("tab", { name: /Nguồn A/ }));
  expect(screen.getByTitle("Nguồn: Nguồn A")).toBeVisible();
  expect(useReportPreviewStore.getState().tabs).toHaveLength(2);
});

it("closes one tab and keeps the others open", async () => {
  useReportPreviewStore.getState().openSource("https://example.com/a", "Nguồn A");
  useReportPreviewStore.getState().openSource("https://example.com/b", "Nguồn B");
  render(<PreviewPane />);

  fireEvent.click(screen.getByRole("button", { name: "Đóng Nguồn A" }));
  await waitFor(() => expect(useReportPreviewStore.getState().tabs).toHaveLength(1));
  expect(screen.getByRole("tab", { name: /Nguồn B/ })).toBeVisible();
});

it("opens an AI-search result as its own tab", async () => {
  useReportPreviewStore.getState().openResearch({
    query: "VIC HOSE",
    summary_markdown: "Kết quả nghiên cứu",
    sources: [{ title: "Nguồn 1", url: "https://example.com/a" }],
  });
  render(<PreviewPane />);

  expect(screen.getByRole("complementary", { name: "VIC HOSE" })).toBeVisible();
  expect(screen.getByText("Kết quả nghiên cứu")).toBeVisible();
  expect(screen.getByRole("link", { name: "Nguồn 1" })).toBeVisible();
});

it("closes every preview when the pane is dismissed", async () => {
  useReportPreviewStore.getState().openArtifact("b".repeat(32));
  useReportPreviewStore.getState().openSource("https://example.com/a", "Nguồn A");
  render(<PreviewPane />);

  fireEvent.click(screen.getByRole("button", { name: "Đóng tất cả bản xem trước" }));
  await waitFor(() => expect(useReportPreviewStore.getState().tabs).toHaveLength(0));
  expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
});

it("places the shared tab strip above a body that fills the preview column", () => {
  useReportPreviewStore.getState().openSource("https://example.com/a", "Nguồn A");
  render(<PreviewPane />);
  const strip = screen.getByRole("tablist");
  const panel = screen.getByRole("tabpanel", { name: "Nguồn A" });
  expect(strip.parentElement).toHaveClass("flex-col");
  expect(panel.parentElement).toHaveClass("flex-1", "min-h-0");
  expect(strip.nextElementSibling).toBe(panel.parentElement);
});

it("resizes by keyboard within bounds and keeps the divider accessible", () => {
  useReportPreviewStore.getState().openSource("https://example.com/a", "Nguồn A");
  render(<PreviewPane />);
  const divider = screen.getByRole("separator", { name: "Điều chỉnh độ rộng khung xem trước" });
  expect(divider).toHaveAttribute("aria-orientation", "vertical");
  fireEvent.keyDown(divider, { key: "ArrowLeft" });
  expect(divider.parentElement).toHaveStyle({ width: "53%" });
  fireEvent.keyDown(divider, { key: "End" });
  fireEvent.keyDown(divider, { key: "ArrowLeft" });
  expect(divider).toHaveAttribute("aria-valuenow", "70");
  fireEvent.keyDown(divider, { key: "Home" });
  fireEvent.keyDown(divider, { key: "ArrowRight" });
  expect(divider.parentElement).toHaveStyle({ width: "30%" });
});

it("drags relative to the chat container and stops resizing after release", () => {
  vi.stubGlobal("PointerEvent", MouseEvent);
  useReportPreviewStore.getState().openSource("https://example.com/a", "Nguồn A");
  render(<div data-testid="layout"><PreviewPane /></div>);
  vi.spyOn(screen.getByTestId("layout"), "getBoundingClientRect").mockReturnValue({ left: 200, right: 1200, width: 1000 } as DOMRect);
  const divider = screen.getByRole("separator");
  divider.setPointerCapture = vi.fn();
  divider.hasPointerCapture = vi.fn(() => true);
  divider.releasePointerCapture = vi.fn();
  fireEvent.pointerDown(divider, { clientX: 720 });
  fireEvent.pointerMove(divider, { clientX: 700 });
  expect(divider.parentElement).toHaveStyle({ width: "50%" });
  fireEvent.pointerMove(divider, { clientX: 0 });
  expect(divider).toHaveAttribute("aria-valuenow", "70");
  fireEvent.pointerMove(divider, { clientX: 1200 });
  expect(divider).toHaveAttribute("aria-valuenow", "30");
  fireEvent.pointerUp(divider);
  fireEvent.pointerMove(divider, { clientX: 0 });
  expect(divider).toHaveAttribute("aria-valuenow", "30");
  expect(divider.releasePointerCapture).toHaveBeenCalledOnce();
});

it("keeps the preview width after the pane is reopened", () => {
  useReportPreviewStore.getState().openSource("https://example.com/a", "Nguồn A");
  const { unmount } = render(<PreviewPane />);
  const divider = screen.getByRole("separator", { name: "Điều chỉnh độ rộng khung xem trước" });
  fireEvent.keyDown(divider, { key: "ArrowLeft" });
  expect(divider.parentElement).toHaveStyle({ width: "53%" });
  expect(localStorage.getItem("qa-preview-width")).toBe("53");
  unmount();
  render(<PreviewPane />);
  expect(screen.getByRole("separator").parentElement).toHaveStyle({ width: "53%" });
});

it("resets the width on double click and shows a drag handle", () => {
  useReportPreviewStore.getState().openSource("https://example.com/a", "Nguồn A");
  render(<PreviewPane />);
  const divider = screen.getByRole("separator", { name: "Điều chỉnh độ rộng khung xem trước" });
  expect(divider).toHaveAttribute("title", "Kéo để đổi độ rộng · nhấp đúp để đặt lại");
  expect(divider.firstElementChild).toHaveAttribute("aria-hidden", "true");
  fireEvent.keyDown(divider, { key: "End" });
  expect(divider.parentElement).toHaveStyle({ width: "70%" });
  fireEvent.doubleClick(divider);
  expect(divider.parentElement).toHaveStyle({ width: "48%" });
  expect(localStorage.getItem("qa-preview-width")).toBe("48");
});

it("returns focus to the source link after the final preview closes", () => {
  render(<><button onClick={() => useReportPreviewStore.getState().openSource("https://example.com/a", "Nguồn A")}>Mở nguồn</button><PreviewPane /></>);

  const trigger = screen.getByRole("button", { name: "Mở nguồn" });
  trigger.focus();
  fireEvent.click(trigger);
  expect(screen.getByRole("tab", { name: "Nguồn A" })).toHaveFocus();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(trigger).toHaveFocus();
});

it("hides the native view while dragging and restores it without reopening the page", () => {
  vi.stubGlobal("PointerEvent", MouseEvent);
  const browser = {
    open: vi.fn().mockResolvedValue(undefined), setBounds: vi.fn(), close: vi.fn(), navigate: vi.fn(), openExternal: vi.fn(),
    onState: vi.fn(() => vi.fn()),
  };
  window.vibeDesktop = { isDesktop: true, sourceBrowser: browser, restartBackend: vi.fn(), getCredentialStatus: vi.fn(), setCredential: vi.fn() };
  useReportPreviewStore.getState().openSource("https://example.com/a", "Nguồn A");
  render(<div data-testid="layout"><PreviewPane /></div>);
  vi.spyOn(screen.getByTestId("layout"), "getBoundingClientRect").mockReturnValue({ left: 200, right: 1200, width: 1000 } as DOMRect);
  const viewport = screen.getByRole("complementary", { name: "Nguồn A" }).lastElementChild!;
  vi.spyOn(viewport, "getBoundingClientRect").mockReturnValue({ x: 700, y: 120, width: 500, height: 600 } as DOMRect);
  fireEvent.resize(window);
  expect(browser.setBounds).toHaveBeenLastCalledWith({ x: 700, y: 120, width: 500, height: 600 });
  const divider = screen.getByRole("separator");
  divider.setPointerCapture = vi.fn();
  divider.hasPointerCapture = vi.fn(() => true);
  divider.releasePointerCapture = vi.fn();
  fireEvent.pointerDown(divider, { button: 2 });
  expect(divider.setPointerCapture).not.toHaveBeenCalled();
  fireEvent.pointerDown(divider, { button: 0 });
  expect(browser.setBounds).toHaveBeenLastCalledWith({ x: 700, y: 120, width: 0, height: 0 });
  fireEvent.pointerMove(divider, { clientX: 700 });
  fireEvent.resize(window);
  expect(browser.setBounds).toHaveBeenLastCalledWith({ x: 700, y: 120, width: 0, height: 0 });
  fireEvent.pointerCancel(divider);
  expect(browser.setBounds).toHaveBeenLastCalledWith({ x: 700, y: 120, width: 500, height: 600 });
  expect(browser.open).toHaveBeenCalledOnce();
  expect(browser.close).not.toHaveBeenCalled();
});

it("switches tabs using arrows and preserves iframe identity and the selected PDF page", async () => {
  useReportPreviewStore.getState().openJob(receipt());
  useReportPreviewStore.getState().openSource("https://example.com/a", "Nguồn A");
  render(<PreviewPane />);
  const sourceFrame = screen.getByTitle("Nguồn: Nguồn A");
  fireEvent.keyDown(screen.getByRole("tab", { name: "Nguồn A" }), { key: "ArrowLeft" });
  expect(screen.getByRole("tab", { name: "research.docx" })).toHaveFocus();
  await screen.findByRole("img", { name: "Xem trước research.docx, trang 1" });
  fireEvent.click(screen.getByRole("button", { name: "Trang tiếp theo" }));
  const secondPage = await screen.findByRole("img", { name: "Xem trước research.docx, trang 2" });
  fireEvent.keyDown(screen.getByRole("tab", { name: "research.docx" }), { key: "End" });
  expect(screen.getByTitle("Nguồn: Nguồn A")).toBe(sourceFrame);
  fireEvent.keyDown(screen.getByRole("tab", { name: "Nguồn A" }), { key: "Home" });
  expect(screen.getByRole("img", { name: "Xem trước research.docx, trang 2" })).toBe(secondPage);
  expect(fetchReportPreviewPage).toHaveBeenCalledTimes(2);
});

it("closes only the active tab on Escape, including research, without cancelling chat", async () => {
  useReportPreviewStore.getState().openJob(receipt());
  useReportPreviewStore.getState().openSource("https://example.com/a", "Nguồn A");
  useReportPreviewStore.getState().openResearch({ query: "VIC", sources: [] });
  render(<PreviewPane />);
  const cancellation = vi.fn();
  document.addEventListener("keydown", cancellation);
  try {
    fireEvent.keyDown(document, { key: "Escape" });
    expect(useReportPreviewStore.getState().tabs.map((tab) => tab.kind)).toEqual(["report", "source"]);
    expect(screen.getByRole("tabpanel", { name: "Nguồn A" })).toBeVisible();
    expect(cancellation).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(useReportPreviewStore.getState().tabs.map((tab) => tab.kind)).toEqual(["report"]);
    await screen.findByRole("img", { name: "Xem trước research.docx, trang 1" });
  } finally {
    document.removeEventListener("keydown", cancellation);
  }
});

it("attaches only the active native source and restores its URL after showing a report", async () => {
  let listener!: (state: SourceBrowserState) => void;
  const unsubscribes: ReturnType<typeof vi.fn>[] = [];
  const browser = {
    open: vi.fn().mockResolvedValue(undefined), setBounds: vi.fn(), close: vi.fn(), navigate: vi.fn(), openExternal: vi.fn(),
    onState: vi.fn((callback: (state: SourceBrowserState) => void) => { listener = callback; const unsubscribe = vi.fn(); unsubscribes.push(unsubscribe); return unsubscribe; }),
  };
  window.vibeDesktop = { isDesktop: true, sourceBrowser: browser, restartBackend: vi.fn(), getCredentialStatus: vi.fn(), setCredential: vi.fn() };
  useReportPreviewStore.getState().openSource("https://example.com/a", "Nguồn A");
  useReportPreviewStore.getState().openSource("https://example.com/b", "Nguồn B");
  render(<PreviewPane />);
  expect(browser.open).toHaveBeenCalledOnce();
  expect(browser.open).toHaveBeenLastCalledWith("https://example.com/b", expect.any(Object));
  act(() => listener({ url: "https://example.com/b/next", title: "Next", loading: false, canGoBack: true, canGoForward: false }));
  act(() => useReportPreviewStore.getState().openJob(receipt()));
  expect(browser.close).toHaveBeenCalledOnce();
  expect(unsubscribes[0]).toHaveBeenCalledOnce();
  await screen.findByRole("img", { name: "Xem trước research.docx, trang 1" });
  fireEvent.click(screen.getByRole("tab", { name: "Nguồn B" }));
  expect(browser.open).toHaveBeenLastCalledWith("https://example.com/b/next", expect.any(Object));
  fireEvent.click(screen.getByRole("button", { name: "Đóng Nguồn A" }));
  expect(browser.close).toHaveBeenCalledOnce();
  act(() => listener({ url: "https://example.com/b/next", title: "Next", loading: false, canGoBack: false, canGoForward: false, closed: true }));
  expect(useReportPreviewStore.getState().tabs.map((tab) => tab.kind)).toEqual(["report"]);
});
