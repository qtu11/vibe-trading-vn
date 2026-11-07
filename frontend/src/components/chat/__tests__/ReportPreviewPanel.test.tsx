import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReportPreviewPanel } from "../ReportPreviewPanel";
import { api, downloadGeneratedReport, fetchGeneratedReport } from "@/lib/api";
import { REPORT_MEDIA_TYPES, type ReportEngineJob, type ReportFormat } from "@/lib/reportEngine";
import { useReportPreviewStore } from "@/stores/reportPreview";

vi.mock("@/lib/api", () => ({ api: { getReportJobForArtifact: vi.fn() }, downloadGeneratedReport: vi.fn(), fetchGeneratedReport: vi.fn() }));

function receipt(formats: ReportFormat[] = ["docx", "pdf", "pptx"]): ReportEngineJob {
  return { job_id: "a".repeat(32), status: "succeeded", formats,
    artifacts: formats.map((format, index) => ({ report_id: String(index + 1).repeat(32), filename: `research.${format}`,
      media_type: REPORT_MEDIA_TYPES[format], download_url: `/api/reports/${String(index + 1).repeat(32)}`, sha256: "c".repeat(64), size_bytes: 1000 })),
    error: null, publication_status: "draft_unverified", created_at: "2026-11-07T00:00:00Z", updated_at: "2026-11-07T00:00:01Z" };
}

beforeEach(() => {
  useReportPreviewStore.getState().close();
  vi.mocked(fetchGeneratedReport).mockReset().mockResolvedValue(new Blob(["%PDF-test"], { type: "application/pdf" }));
  vi.mocked(api.getReportJobForArtifact).mockReset();
  vi.mocked(downloadGeneratedReport).mockReset().mockResolvedValue(undefined);
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:report-preview") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
});

it("previews the PDF from a clicked DOCX handle and keeps all three downloads in its footer", async () => {
  const job = receipt();
  vi.mocked(api.getReportJobForArtifact).mockResolvedValue(job);
  useReportPreviewStore.getState().openArtifact(job.artifacts[0].report_id);
  render(<ReportPreviewPanel />);
  expect(await screen.findByTitle("Xem trước research.docx")).toHaveAttribute("src", "blob:report-preview#toolbar=0&navpanes=0");
  expect(api.getReportJobForArtifact).toHaveBeenCalledWith(job.artifacts[0].report_id, expect.any(AbortSignal));
  expect(fetchGeneratedReport).toHaveBeenCalledWith(job.artifacts[1], expect.any(AbortSignal));
  for (const format of ["DOCX", "PDF", "PPTX"]) expect(screen.getByRole("button", { name: `Tải ${format}` })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Tải PPTX" }));
  await waitFor(() => expect(downloadGeneratedReport).toHaveBeenCalledWith(job.artifacts[2].report_id, "research.pptx"));
});

it("closes on Escape without propagating cancellation, restores focus and releases bytes", async () => {
  const trigger = document.createElement("button"); document.body.append(trigger); trigger.focus();
  useReportPreviewStore.getState().openJob(receipt());
  render(<ReportPreviewPanel />);
  await screen.findByTitle("Xem trước research.docx");
  expect(screen.getByRole("button", { name: "Đóng bản xem trước" })).toHaveFocus();
  const cancellation = vi.fn(); document.addEventListener("keydown", cancellation);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(useReportPreviewStore.getState().selection).toBeNull();
  expect(cancellation).not.toHaveBeenCalled();
  expect(trigger).toHaveFocus();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:report-preview");
  document.removeEventListener("keydown", cancellation); trigger.remove();
});

it("keeps Word downloadable when preview export failed and disables unavailable formats", async () => {
  const job = receipt(["docx"]); job.status = "partial"; job.formats.push("pdf", "pptx");
  job.error = { code: "PARTIAL_EXPORT", message: "Thiếu PDF và PPTX" };
  useReportPreviewStore.getState().openJob(job);
  render(<ReportPreviewPanel />);
  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  expect(screen.getByText(/Bản xem trước PDF chưa sẵn sàng/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Tải DOCX" })).toBeEnabled();
  expect(screen.getByRole("button", { name: /Tải PDF/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: /Tải PPTX/ })).toBeDisabled();
  expect(fetchGeneratedReport).not.toHaveBeenCalled();
});

it("aborts stale requests on another selection and never shows their response", async () => {
  let resolveOld: (value: ReportEngineJob) => void = () => {};
  vi.mocked(api.getReportJobForArtifact).mockReturnValue(new Promise((resolve) => { resolveOld = resolve; }));
  useReportPreviewStore.getState().openArtifact("b".repeat(32));
  const { unmount } = render(<ReportPreviewPanel />);
  const signal = vi.mocked(api.getReportJobForArtifact).mock.calls[0][1]!;
  act(() => useReportPreviewStore.getState().openJob(receipt()));
  await screen.findByTitle("Xem trước research.docx");
  expect(signal.aborted).toBe(true);
  await act(async () => resolveOld({ ...receipt(), artifacts: [] }));
  expect(screen.getByTitle("Xem trước research.docx")).toBeVisible();
  expect(fetchGeneratedReport).toHaveBeenCalledOnce();
  unmount();
  expect(vi.mocked(fetchGeneratedReport).mock.calls[0][1]?.aborted).toBe(true);
});

it("shows a preview fetch error while keeping exports available", async () => {
  vi.mocked(fetchGeneratedReport).mockRejectedValue(new Error("Không thể đọc PDF"));
  useReportPreviewStore.getState().openJob(receipt());
  render(<ReportPreviewPanel />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Không thể đọc PDF");
  expect(screen.getByRole("button", { name: "Tải DOCX" })).toBeEnabled();
});
