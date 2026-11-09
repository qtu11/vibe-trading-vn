/** Server-rendered draft documents. Download handles are opaque IDs, never paths. */
export const REPORT_MEDIA_TYPES = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
} as const;
export type ReportFormat = keyof typeof REPORT_MEDIA_TYPES;
export type ReportJobStatus = "queued" | "running" | "succeeded" | "partial" | "failed";
export interface ReportArtifact {
  job_id?: string;
  report_id: string;
  download_url: string;
  filename: string;
  media_type: typeof REPORT_MEDIA_TYPES[ReportFormat];
  sha256: string;
  size_bytes: number;
}
export interface ReportEngineJob {
  job_id: string;
  status: ReportJobStatus;
  formats: ReportFormat[];
  artifacts: ReportArtifact[];
  error: { code: string; message: string } | null;
  publication_status: "draft_unverified" | "simulated_demo";
  warnings?: string[];
  minimum_pages?: number;
  pdf_pages?: number | null;
  created_at: string;
  updated_at: string;
}
export interface ReportArtifactBytes { blob: Blob; filename: string; format: ReportFormat; reportId: string }
export const MAX_REPORT_ARTIFACT_BYTES = 32 * 1024 * 1024;
export const isReportHandle = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{32}$/.test(value);
export const isResearchRevisionHandle = (value: unknown): value is string => typeof value === "string" && /^rr_[0-9a-f]{32}$/.test(value);
export const isReportFormat = (value: unknown): value is ReportFormat => value === "pdf" || value === "docx" || value === "pptx";
export function artifactFormat(artifact: ReportArtifact): ReportFormat | null {
  return (Object.keys(REPORT_MEDIA_TYPES) as ReportFormat[]).find((format) => artifact.media_type === REPORT_MEDIA_TYPES[format]) ?? null;
}
export function safeReportFilename(value: unknown, format: ReportFormat): value is string {
  return typeof value === "string" && value.length > format.length + 1 && value.length <= 180
    && !/[\x00-\x1f\x7f/\\]/.test(value) && !value.startsWith(".")
    && value.toLowerCase().endsWith(`.${format}`);
}
export function validReportArtifact(value: unknown): value is ReportArtifact {
  if (!value || typeof value !== "object") return false;
  const artifact = value as ReportArtifact, format = artifactFormat(artifact);
  return !!format && isReportHandle(artifact.report_id)
    && (artifact.job_id === undefined || isReportHandle(artifact.job_id))
    && artifact.download_url === `/api/reports/${artifact.report_id}`
    && safeReportFilename(artifact.filename, format) && /^[0-9a-f]{64}$/.test(artifact.sha256)
    && Number.isSafeInteger(artifact.size_bytes) && artifact.size_bytes > 0 && artifact.size_bytes <= MAX_REPORT_ARTIFACT_BYTES;
}
export function validReportJob(value: unknown): value is ReportEngineJob {
  if (!value || typeof value !== "object") return false;
  const job = value as ReportEngineJob;
  const validPageCount = (pages: unknown) => Number.isSafeInteger(pages) && Number(pages) >= 1 && Number(pages) <= 2000;
  const depthIncomplete = job.minimum_pages !== undefined && job.minimum_pages > 1 && (
    job.error?.code === "PAGE_COUNT_UNAVAILABLE" && job.pdf_pages === null
    || job.error?.code === "INSUFFICIENT_REPORT_DEPTH" && validPageCount(job.pdf_pages) && job.pdf_pages! < job.minimum_pages
  );
  return isReportHandle(job.job_id) && ["queued", "running", "succeeded", "partial", "failed"].includes(job.status)
    && ["draft_unverified", "simulated_demo"].includes(job.publication_status) && Array.isArray(job.formats)
    && job.formats.length > 0 && job.formats.length <= 3 && job.formats.every(isReportFormat)
    && new Set(job.formats).size === job.formats.length && Array.isArray(job.artifacts)
    && job.artifacts.length <= 3 && job.artifacts.every(validReportArtifact)
    && new Set(job.artifacts.map((artifact) => artifactFormat(artifact))).size === job.artifacts.length
    && job.artifacts.every((artifact) => job.formats.includes(artifactFormat(artifact)!))
    && (job.minimum_pages === undefined || validPageCount(job.minimum_pages))
    && (job.pdf_pages === undefined || job.pdf_pages === null || validPageCount(job.pdf_pages))
    && (job.status === "succeeded" ? job.artifacts.length === job.formats.length && (job.minimum_pages === undefined || job.minimum_pages <= 1 || validPageCount(job.pdf_pages) && job.pdf_pages! >= job.minimum_pages)
      : job.status === "partial" ? job.artifacts.length > 0 && (job.artifacts.length < job.formats.length || depthIncomplete)
      : job.artifacts.length === 0)
    && (job.error === null || (typeof job.error?.code === "string" && typeof job.error?.message === "string"))
    && (job.status === "succeeded" ? job.error === null
      : job.status === "partial" || job.status === "failed" ? job.error !== null : true)
    && (job.warnings === undefined || (Array.isArray(job.warnings) && job.warnings.every((warning) => typeof warning === "string")))
    && typeof job.created_at === "string" && typeof job.updated_at === "string";
}
/** A model-written fence can name a job, but cannot supply download destinations. */
export function parseReportArtifactFence(code: string): string | null {
  if (code.length > 65536) return null;
  try {
    const value: unknown = JSON.parse(code);
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const receipt = value as Record<string, unknown>;
    if (receipt.type !== undefined && receipt.type !== "report_artifact") return null;
    return isReportHandle(receipt.job_id) ? receipt.job_id : null;
  } catch { return null; }
}
