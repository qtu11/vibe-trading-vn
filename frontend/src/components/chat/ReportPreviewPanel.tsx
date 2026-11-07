import { useEffect, useRef, useState } from "react";
import { AlertCircle, ChevronLeft, ChevronRight, Download, FileText, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { api, downloadGeneratedReport, fetchReportPreviewPage } from "@/lib/api";
import { artifactFormat, type ReportArtifact, type ReportEngineJob, type ReportFormat } from "@/lib/reportEngine";
import { useReportPreviewStore } from "@/stores/reportPreview";

const FORMATS: ReportFormat[] = ["docx", "pdf", "pptx"];

export function ReportPreviewPanel() {
  const selection = useReportPreviewStore((state) => state.selection);
  const close = useReportPreviewStore((state) => state.close);
  const [job, setJob] = useState<ReportEngineJob | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [pageIndex, setPageIndex] = useState(0), [pages, setPages] = useState(0);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!selection) return;
    const previouslyFocused = document.activeElement;
    closeRef.current?.focus();
    const onEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      close();
    };
    document.addEventListener("keydown", onEscape, true);
    return () => {
      document.removeEventListener("keydown", onEscape, true);
      if (previouslyFocused instanceof HTMLElement && previouslyFocused.isConnected) previouslyFocused.focus();
    };
  }, [!!selection, close]);

  useEffect(() => {
    if (!selection) return;
    const controller = new AbortController();
    setJob(null);
    setPreviewUrl(null);
    setError(null);
    setLoading(true);
    setDownloadingId(null);
    setPageIndex(0); setPages(0);

    async function load() {
      try {
        const receipt = "job" in selection!
          ? selection.job
          : await api.getReportJobForArtifact(selection!.reportId, controller.signal);
        if (controller.signal.aborted) return;
        setJob(receipt);
        const pdf = receipt.artifacts.find((artifact) => artifactFormat(artifact) === "pdf");
        if (!pdf) {
          setError("Bản xem trước PDF chưa sẵn sàng. Bạn vẫn có thể tải các định dạng đã xuất bên dưới.");
          setLoading(false);
          return;
        }
        const count = await api.getReportPreviewPages(pdf.report_id, controller.signal);
        if (controller.signal.aborted) return;
        setPages(count);
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : "Không thể mở bản xem trước");
          setLoading(false);
        }
      }
    }
    void load();
    return () => {
      controller.abort();
    };
  }, [selection]);

  useEffect(() => {
    const pdf = job?.artifacts.find((artifact) => artifactFormat(artifact) === "pdf");
    if (!selection || !pdf || !pages) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setLoading(true); setError(null); setPreviewUrl(null);
    void fetchReportPreviewPage(pdf.report_id, pageIndex, controller.signal).then((blob) => {
      if (controller.signal.aborted) return;
      objectUrl = URL.createObjectURL(blob); setPreviewUrl(objectUrl);
    }).catch((err) => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Không thể đọc trang xem trước");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [selection, job, pages, pageIndex]);

  async function handleDownload(artifact: ReportArtifact) {
    setDownloadingId(artifact.report_id);
    try {
      await downloadGeneratedReport(artifact.report_id, artifact.filename);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Tải tài liệu thất bại");
    } finally {
      setDownloadingId((current) => current === artifact.report_id ? null : current);
    }
  }

  if (!selection) return null;
  const title = job?.artifacts.find((artifact) => artifactFormat(artifact) === "docx")?.filename
    ?? job?.artifacts[0]?.filename ?? "Báo cáo nghiên cứu";

  return (
    <aside aria-labelledby="report-preview-title" className="z-20 flex h-full w-[48%] min-w-[22rem] max-w-3xl shrink-0 flex-col border-l border-red-900/15 bg-background shadow-xl max-lg:absolute max-lg:inset-0 max-lg:w-full max-lg:min-w-0 max-lg:max-w-none">
      <header className="flex items-center gap-3 border-b border-red-900/10 bg-[#641C24] px-4 py-3 text-white">
        <img src="/shrimp-vest-logo.png" alt="Logo tôm đỏ Vibe-Trading" className="h-10 w-10 shrink-0 object-contain" />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold tracking-[0.15em] text-red-100">VIBE RESEARCH</p>
          <h2 id="report-preview-title" className="truncate text-sm font-semibold" title={title}>{title}</h2>
        </div>
        <button ref={closeRef} type="button" onClick={close} aria-label="Đóng bản xem trước" className="shrink-0 rounded-lg p-2 text-red-100 transition-colors hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white">
          <X aria-hidden="true" className="h-4 w-4" />
        </button>
      </header>
      <div className="border-b border-border px-4 py-2 text-[11px] text-muted-foreground">
        {job?.publication_status === "simulated_demo" ? "Dữ liệu giả lập" : "Dự thảo nghiên cứu"} · Xem trước bản PDF cùng bộ tài liệu.
      </div>
      {job?.status === "partial" && <p role="alert" className="border-b border-amber-500/20 bg-amber-500/10 px-4 py-2 text-xs text-amber-800 dark:text-amber-200">{job.error?.message || "Một số định dạng chưa xuất được."}</p>}
      {pages > 0 && <nav aria-label="Trang báo cáo" className="flex shrink-0 items-center justify-center gap-3 border-b border-border px-4 py-2">
        <button type="button" aria-label="Trang trước" disabled={pageIndex === 0} onClick={() => setPageIndex((current) => current - 1)} className="rounded-lg border p-1.5 hover:bg-muted disabled:opacity-35"><ChevronLeft aria-hidden="true" className="h-4 w-4" /></button>
        <span aria-live="polite" className="text-xs tabular-nums">Trang {pageIndex + 1} / {pages}</span>
        <button type="button" aria-label="Trang tiếp theo" disabled={pageIndex + 1 >= pages} onClick={() => setPageIndex((current) => current + 1)} className="rounded-lg border p-1.5 hover:bg-muted disabled:opacity-35"><ChevronRight aria-hidden="true" className="h-4 w-4" /></button>
      </nav>}
      <div className="min-h-0 flex-1 overflow-auto bg-muted/40 p-3">
        {loading ? <div role="status" className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />Đang mở tài liệu...</div>
          : error ? <div role="alert" className="flex h-full flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-red-900/20 bg-background px-6 text-center text-sm text-muted-foreground"><AlertCircle aria-hidden="true" className="h-6 w-6 text-red-700" /><p>{error}</p></div>
          : previewUrl && <img alt={`Xem trước ${title}, trang ${pageIndex + 1}`} src={previewUrl} onError={() => setError("Không thể hiển thị trang xem trước. Bạn có thể tải tài liệu bên dưới.")} className="mx-auto h-auto w-full rounded-xl border border-border bg-white" />}
      </div>
      <footer className="shrink-0 border-t border-border bg-background px-4 py-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-medium"><FileText aria-hidden="true" className="h-3.5 w-3.5 text-red-700" />Tải tài liệu</div>
        <div className="grid grid-cols-3 gap-2">
          {FORMATS.map((format) => {
            const artifact = job?.artifacts.find((item) => artifactFormat(item) === format);
            const downloading = artifact && downloadingId === artifact.report_id;
            return <button key={format} type="button" disabled={!artifact || !!downloadingId} onClick={() => artifact && void handleDownload(artifact)} aria-label={`Tải ${format.toUpperCase()}${artifact ? "" : " — chưa sẵn sàng"}`} className="flex min-w-0 flex-col items-center gap-1 rounded-xl border border-red-900/15 bg-red-50 px-2 py-2.5 text-red-900 transition-colors hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-45 dark:bg-red-950/30 dark:text-red-100 dark:hover:bg-red-950/60">
              <span className="flex items-center gap-1.5 text-xs font-semibold">{downloading ? <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" /> : <Download aria-hidden="true" className="h-3.5 w-3.5" />}{format.toUpperCase()}</span>
              <span className="text-[10px] opacity-75">{artifact ? `${(artifact.size_bytes / 1024).toFixed(0)} KB` : "Chưa sẵn sàng"}</span>
            </button>;
          })}
        </div>
      </footer>
    </aside>
  );
}
