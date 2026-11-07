import { REPORT_MEDIA_TYPES, validReportJob, type ReportArtifact, type ReportEngineJob, type ReportFormat } from "../reportEngine";

const artifact = (format: ReportFormat): ReportArtifact => ({
  report_id: "b".repeat(32), download_url: `/api/reports/${"b".repeat(32)}`,
  filename: `research.${format}`, sha256: "c".repeat(64), size_bytes: 1000,
  media_type: REPORT_MEDIA_TYPES[format],
});

it("accepts all three document formats and validates optional owning job handles", () => {
  const value = job(); value.formats.push("pptx"); value.artifacts.push(artifact("pptx"));
  expect(validReportJob(value)).toBe(true);
  value.artifacts[2].job_id = "invalid";
  expect(validReportJob(value)).toBe(false);
});
const job = (): ReportEngineJob => ({
  job_id: "a".repeat(32), status: "succeeded", formats: ["docx", "pdf"],
  artifacts: [artifact("docx"), artifact("pdf")], error: null,
  publication_status: "draft_unverified", created_at: "2026-11-07T00:00:00Z", updated_at: "2026-11-07T00:00:01Z",
});

it("accepts available downloads when one requested format failed", () => {
  const value = job();
  value.status = "partial"; value.artifacts = [artifact("docx")];
  value.error = { code: "PARTIAL_EXPORT", message: "PDF unavailable" };
  expect(validReportJob(value)).toBe(true);
  value.error = null;
  expect(validReportJob(value)).toBe(false);
});

it("rejects duplicate artifacts masquerading as both formats", () => {
  const value = job(); value.artifacts = [artifact("docx"), artifact("docx")];
  expect(validReportJob(value)).toBe(false);
});

it("accepts labelled simulation but never model self-certification", () => {
  const value = job(); value.publication_status = "simulated_demo";
  expect(validReportJob(value)).toBe(true);
  expect(validReportJob({ ...value, publication_status: "certified" })).toBe(false);
});

it("keeps completed and failed receipts consistent with their errors", () => {
  const value = job(); expect(validReportJob(value)).toBe(true);
  value.error = { code: "FAILED", message: "unavailable" };
  expect(validReportJob(value)).toBe(false);
  value.status = "failed"; value.artifacts = [];
  expect(validReportJob(value)).toBe(true);
  value.error = null;
  expect(validReportJob(value)).toBe(false);
});
