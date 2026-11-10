import { fireEvent, render, screen } from "@testing-library/react";
import ReportArtifactCard from "../ReportArtifactCard";
import { api } from "@/lib/api";
import type { ReportEngineJob } from "@/lib/reportEngine";
import { useReportPreviewStore } from "@/stores/reportPreview";

vi.mock("@/lib/api", () => ({ api: { getReportJob: vi.fn() }, downloadGeneratedReport: vi.fn() }));

const receipt = (): ReportEngineJob => ({
  job_id: "a".repeat(32), status: "partial", formats: ["docx", "pdf"],
  artifacts: [{ report_id: "b".repeat(32), filename: "research.docx", media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    download_url: `/api/reports/${"b".repeat(32)}`, sha256: "c".repeat(64), size_bytes: 1000 }],
  error: { code: "PARTIAL_EXPORT", message: "Thiếu định dạng PDF" }, publication_status: "draft_unverified",
  created_at: "2026-11-07T00:00:00Z", updated_at: "2026-11-07T00:00:01Z",
});

it("shows partial export warning, shrimp logo, and opens Word in the preview sidebar", async () => {
  vi.mocked(api.getReportJob).mockResolvedValue(receipt());
  render(<ReportArtifactCard code={JSON.stringify({ job_id: "a".repeat(32) })} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Thiếu định dạng PDF");
  const word = screen.getByRole("button", { name: /Xem Word/ });
  expect(word).toBeVisible();
  expect(screen.queryByRole("button", { name: /Xem PDF/ })).not.toBeInTheDocument();
  expect(screen.getByRole("img", { name: /tôm đỏ/ })).toBeVisible();
  expect(screen.queryByText("Báo cáo chính thức")).not.toBeInTheDocument();
  fireEvent.click(word);
  expect(useReportPreviewStore.getState().tabs).toHaveLength(1);
  expect(useReportPreviewStore.getState().tabs[0].selection).toEqual({ kind: "report", job: receipt() });
  expect(useReportPreviewStore.getState().activeId).toBe(useReportPreviewStore.getState().tabs[0].id);
});

it("labels simulated documents visibly", async () => {
  vi.mocked(api.getReportJob).mockResolvedValue({ ...receipt(), publication_status: "simulated_demo" });
  render(<ReportArtifactCard code={JSON.stringify({ job_id: "a".repeat(32) })} />);
  expect(await screen.findByText("Dữ liệu giả lập")).toBeVisible();
});
