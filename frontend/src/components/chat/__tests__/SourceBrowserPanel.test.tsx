import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { SourceBrowserState } from "@/desktop";
import { useReportPreviewStore } from "@/stores/reportPreview";
import { SourceBrowserPanel } from "../SourceBrowserPanel";
import { SourceLink } from "../SourceLink";
import { MarkdownContent } from "../MessageBubble";

beforeEach(() => { useReportPreviewStore.getState().close(); delete window.vibeDesktop; });
afterEach(() => { useReportPreviewStore.getState().close(); delete window.vibeDesktop; });

it("opens source links beside chat and closes with Escape while restoring focus", () => {
  render(<><SourceLink href="https://example.com/report">Báo cáo</SourceLink><SourceBrowserPanel /></>);
  const link = screen.getByRole("link", { name: "Báo cáo" }); link.focus();
  fireEvent.click(link);
  expect(screen.getByRole("complementary", { name: "Báo cáo" })).toBeVisible();
  expect(screen.getByTitle("Nguồn: Báo cáo")).toHaveAttribute("src", "https://example.com/report");
  expect(screen.getByRole("button", { name: "Đóng trình duyệt nguồn" })).toHaveFocus();
  const cancelChat = vi.fn(); document.addEventListener("keydown", cancelChat);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(useReportPreviewStore.getState().selection).toBeNull();
  expect(cancelChat).not.toHaveBeenCalled();
  expect(link).toHaveFocus();
  document.removeEventListener("keydown", cancelChat);
});

it("routes Markdown sources to the browser and document handles to report preview", () => {
  render(<MarkdownContent streaming content={`[Nguồn](https://example.com/page) [Word](/api/reports/${"a".repeat(32)})`} />);
  fireEvent.click(screen.getByRole("link", { name: "Nguồn" }));
  expect(useReportPreviewStore.getState().selection).toEqual({ sourceUrl: "https://example.com/page", title: "Nguồn" });
  fireEvent.click(screen.getByRole("link", { name: "Word" }));
  expect(useReportPreviewStore.getState().selection).toEqual({ reportId: "a".repeat(32) });
});

it("rejects executable URLs and URLs with credentials at the selection boundary", () => {
  for (const url of ["javascript:alert(1)", "file:///secret", "https://user:password@example.com/page", "not a URL"]) {
    useReportPreviewStore.getState().openSource(url);
    expect(useReportPreviewStore.getState().selection).toBeNull();
  }
});

it("controls the isolated desktop browser and releases it when a document replaces it", async () => {
  let listener!: (state: SourceBrowserState) => void;
  const unsubscribe = vi.fn();
  const browser = { open: vi.fn().mockResolvedValue(undefined), setBounds: vi.fn(), close: vi.fn(), navigate: vi.fn(), openExternal: vi.fn(),
    onState: vi.fn((callback) => { listener = callback; return unsubscribe; }) };
  window.vibeDesktop = { isDesktop: true, sourceBrowser: browser, restartBackend: vi.fn(), getCredentialStatus: vi.fn(), setCredential: vi.fn() };
  useReportPreviewStore.getState().openSource("https://example.com/report", "Research");
  render(<SourceBrowserPanel />);
  expect(browser.open).toHaveBeenCalledWith("https://example.com/report", expect.objectContaining({ x: 0, y: 0 }));
  expect(screen.queryByTitle("Nguồn: Research")).not.toBeInTheDocument();
  act(() => listener({ url: "https://example.com/next", title: "Next", loading: false, canGoBack: true, canGoForward: false }));
  fireEvent.click(screen.getByRole("button", { name: "Quay lại" }));
  expect(browser.navigate).toHaveBeenCalledWith("back");
  fireEvent.click(screen.getByRole("button", { name: "Tải lại nguồn" }));
  expect(browser.navigate).toHaveBeenCalledWith("reload");
  fireEvent.click(screen.getByRole("link", { name: "Mở nguồn bằng trình duyệt ngoài" }));
  expect(browser.openExternal).toHaveBeenCalledWith("https://example.com/next");
  act(() => useReportPreviewStore.getState().openArtifact("b".repeat(32)));
  await waitFor(() => expect(browser.close).toHaveBeenCalledOnce());
  expect(unsubscribe).toHaveBeenCalledOnce();
});

it("shows desktop errors and handles Escape from the native page", async () => {
  let listener!: (state: SourceBrowserState) => void;
  window.vibeDesktop = { isDesktop: true, restartBackend: vi.fn(), getCredentialStatus: vi.fn(), setCredential: vi.fn(),
    sourceBrowser: { open: vi.fn().mockRejectedValue(new Error("rejected")), setBounds: vi.fn(), close: vi.fn(), navigate: vi.fn(), openExternal: vi.fn(), onState: (callback) => { listener = callback; return vi.fn(); } } };
  useReportPreviewStore.getState().openSource("https://example.com/report");
  render(<SourceBrowserPanel />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Không thể mở nguồn");
  act(() => listener({ url: "https://example.com/report", title: "", loading: false, canGoBack: false, canGoForward: false, closed: true }));
  expect(useReportPreviewStore.getState().selection).toBeNull();
});
