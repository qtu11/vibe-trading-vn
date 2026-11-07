import { useEffect, useState } from "react";
import { FileText, CheckCircle2, AlertCircle, PanelRightOpen } from "lucide-react";
import { api } from "@/lib/api";
import {
  parseReportArtifactFence,
  type ReportEngineJob,
} from "@/lib/reportEngine";
import { useReportPreviewStore } from "@/stores/reportPreview";

export default function ReportArtifactCard({ code }: { code: string }) {
  const [job, setJob] = useState<ReportEngineJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const openPreview = useReportPreviewStore((state) => state.openJob);

  const jobId = parseReportArtifactFence(code);

  useEffect(() => {
    setJob(null);
    setError(null);
    setLoading(true);
    if (!jobId) {
      setError("Mã báo cáo không hợp lệ");
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    api
      .getReportJob(jobId, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setJob(data);
        setLoading(false);
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : "Không thể tải thông tin báo cáo");
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [jobId]);

  if (!jobId) {
    return (
      <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">
        Dữ liệu nhận diện báo cáo không đúng định dạng.
      </div>
    );
  }

  if (loading) {
    return (
      <div className="my-2 flex items-center gap-2.5 rounded-lg border border-border/80 bg-card/60 p-3.5 text-xs text-muted-foreground animate-pulse">
        <FileText className="h-4 w-4 text-primary" />
        <span>Đang kiểm tra và chuẩn bị liên kết tải báo cáo...</span>
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="my-2 flex items-center gap-2 rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
        <AlertCircle className="h-4 w-4 text-amber-500" />
        <span>Mã báo cáo: {jobId.slice(0, 8)}... (Chưa sẵn sàng tải tự động)</span>
      </div>
    );
  }

  if (job.status === "failed") {
    const errorMsg = typeof job.error === "string"
      ? job.error
      : job.error?.message || job.error?.code || "Lỗi không xác định";

    return (
      <div className="my-2 flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">
        <AlertCircle className="h-4 w-4" />
        <span>Tạo báo cáo thất bại: {errorMsg}</span>
      </div>
    );
  }

  if (job.status === "queued" || job.status === "running") {
    return <div role="status" className="my-2 rounded-xl border border-red-200 bg-red-50 p-4 text-xs text-red-900">Báo cáo đang được tạo. Tải lại khi hoàn tất.</div>;
  }

  const isPartial = job.status === "partial";
  const isDemo = job.publication_status === "simulated_demo";

  return (
    <div className="my-3 overflow-hidden rounded-2xl border border-red-400/30 bg-gradient-to-br from-[#391111] via-[#5C1717] to-[#251010] text-white shadow-lg">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <img src="/shrimp-vest-logo.png" alt="Logo tôm đỏ Vibe-Trading" className="h-9 w-9 rounded-lg object-contain" />
          <span className="text-xs font-semibold tracking-wider text-red-100">
            VIBE RESEARCH • BÁO CÁO PHÂN TÍCH
          </span>
        </div>
        <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-medium text-red-100">
          {isDemo ? "Dữ liệu giả lập" : "Dự thảo nghiên cứu"}
        </span>
      </div>

      <div className="p-4">
        <div className="mb-3 flex items-start justify-between">
          <div>
            <button type="button" onClick={() => openPreview(job)} className="text-left text-sm font-bold text-white underline-offset-4 hover:underline focus-visible:rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-white">
              Tài liệu Báo cáo Tài chính & Định giá
            </button>
            <p className="mt-0.5 text-xs text-red-100/80">
              Bấm vào tài liệu để xem trước ở sidebar bên phải.
            </p>
          </div>
          {isPartial ? <AlertCircle className="h-4 w-4 text-amber-300" /> : <CheckCircle2 className="h-4 w-4 text-red-200" />}
        </div>

        {isPartial && <p role="alert" className="mb-3 rounded-lg bg-amber-300/10 p-2 text-xs text-amber-100">{job.error?.message || "Một định dạng chưa xuất được. Bạn có thể tải tài liệu đã sẵn sàng."}</p>}

        <div className="mt-3 flex flex-wrap gap-2.5">
          <button type="button" onClick={() => openPreview(job)} className="flex items-center gap-2 rounded-lg bg-red-600 px-3.5 py-2 text-xs font-semibold text-white transition-colors hover:bg-red-500"><PanelRightOpen className="h-3.5 w-3.5" aria-hidden="true" />Xem trước tài liệu</button>
          {job.artifacts.map((art) => {
            const isDocx = art.filename.toLowerCase().endsWith(".docx");
            const isPdf = art.filename.toLowerCase().endsWith(".pdf");
            const formatLabel = isDocx ? "Xem Word (DOCX)" : isPdf ? "Xem PDF" : "Xem PowerPoint (PPTX)";
            const sizeLabel = `${(art.size_bytes / 1024).toFixed(0)} KB`;

            return (
              <button
                key={art.report_id}
                type="button"
                onClick={() => openPreview(job)}
                className={`group flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs font-semibold transition-all ${
                  isPdf
                    ? "bg-red-600 text-white hover:bg-red-500 hover:shadow-md hover:shadow-red-600/20"
                    : "border border-white/20 bg-white/5 text-white hover:bg-white/10"
                }`}
              >
                <FileText className="h-3.5 w-3.5" aria-hidden="true" />
                <span>{formatLabel}</span>
                <span className="text-[10px] opacity-70">({sizeLabel})</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="border-t border-white/10 bg-black/20 px-4 py-1.5 text-[10px] text-red-100/70">
        Kiểm tra ngày dữ liệu, giả định và điều kiện khuyến nghị trước khi sử dụng.
      </div>
    </div>
  );
}
