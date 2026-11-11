import { useEffect, useId, useRef, useState } from "react";
import { AlertCircle, ChevronLeft, ChevronRight, Download, FileText, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { api, downloadGeneratedReport, fetchReportPreviewPage } from "@/lib/api";
import { artifactFormat, type ReportArtifact, type ReportEngineJob, type ReportFormat } from "@/lib/reportEngine";
import { useReportPreviewStore } from "@/stores/reportPreview";

const FORMATS: ReportFormat[] = ["docx", "pdf", "pptx"];

/**
 * The document preview for one tab.
 *
 * The pane mounts one panel per open tab and passes `tabId`, so the panel
 * binds to that one document: its loaded state and its in-flight request
 * survive a switch to another tab. Without a `tabId` the panel follows
 * whichever tab is active, which is what a standalone render wants.
 */
export function ReportPreviewPanel({ tabId }: { tabId?: string }) {
  const tab = useReportPreviewStore((state) => {
    if (tabId) return state.tabs.find((item) => item.id === tabId) ?? null;
    return state.activeId ? state.tabs.find((item) => item.id === state.activeId) ?? null : null;
  });
  const selection = tab && tab.kind === "report" && tab.selection.kind === "report" ? tab.selection : null;
  const closeTab = useReportPreviewStore((state) => state.closeTab);
  const [job, setJob] = useState<ReportEngineJob | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [pageIndex, setPageIndex] = useState(0), [pages, setPages] = useState(0);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useEffect(() => {
    if (!selection || tabId) return;
    const previouslyFocused = document.activeElement;
    closeRef.current?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      closeTab(tab!.id);
    };
    document.addEventListener("keydown", escape, true);
    return () => {
      document.removeEventListener("keydown", escape, true);
      if (previouslyFocused instanceof HTMLElement && previouslyFocused.isConnected) previouslyFocused.focus();
    };
  }, [!!selection, tab, tabId, closeTab]);

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
        const current = selection!;
        const receipt = current.job
          ? current.job
          : await api.getReportJobForArtifact(current.reportId!, controller.signal);
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
    <aside aria-labelledby={titleId} className="flex h-full min-h-0 w-full flex-col bg-surface-base">
      <header className="flex items-center gap-3 border-b border-report-brand bg-report-brand px-4 py-3 text-report-ink">
        <img src="/shrimp-vest-logo.png" alt="Logo tôm đỏ Vibe-Trading" className="h-10 w-10 shrink-0 object-contain" />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-report-ink/70">VIBE RESEARCH</p>
          <h2 id={titleId} className="truncate text-sm font-semibold" title={title}>{title}</h2>
        </div>
        <button ref={closeRef} type="button" onClick={() => closeTab(tab!.id)} aria-label="Đóng bản xem trước" className="vt-focus-visible shrink-0 rounded-lg p-2 text-report-ink/70 transition-colors duration-fast hover:bg-white/10 hover:text-report-ink">
          <X aria-hidden="true" className="h-4 w-4" />
        </button>
      </header>
      <div className="border-b border-hairline bg-surface-sidebar px-4 py-2 text-[11px] text-ink-muted">
        {job?.publication_status === "simulated_demo" ? "Dữ liệu giả lập" : "Dự thảo nghiên cứu"} · Xem trước bản PDF cùng bộ tài liệu.
      </div>
      {job?.status === "partial" && <p role="alert" className="border-b border-warning/25 bg-warning/10 px-4 py-2 text-xs text-warning">{job.error?.message || "Một số định dạng chưa xuất được."}</p>}
      {pages > 0 && <nav aria-label="Trang báo cáo" className="flex shrink-0 items-center justify-center gap-3 border-b border-hairline px-4 py-2">
        <button type="button" aria-label="Trang trước" disabled={pageIndex === 0} onClick={() => setPageIndex((current) => current - 1)} className="vt-focus-visible rounded-lg border border-hairline p-1.5 transition-colors duration-fast hover:bg-muted disabled:opacity-35"><ChevronLeft aria-hidden="true" className="h-4 w-4" /></button>
        <span aria-live="polite" className="vt-num text-xs text-ink-secondary">Trang {pageIndex + 1} / {pages}</span>
        <button type="button" aria-label="Trang tiếp theo" disabled={pageIndex + 1 >= pages} onClick={() => setPageIndex((current) => current + 1)} className="vt-focus-visible rounded-lg border border-hairline p-1.5 transition-colors duration-fast hover:bg-muted disabled:opacity-35"><ChevronRight aria-hidden="true" className="h-4 w-4" /></button>
      </nav>}
      <div className="min-h-0 flex-1 overflow-auto bg-surface-sunken p-3">
        {loading ? <div role="status" className="flex h-full items-center justify-center gap-2 text-sm text-ink-muted"><Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />Đang mở tài liệu...</div>
          : error ? <div role="alert" className="flex h-full flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-danger/25 bg-surface-panel px-6 text-center text-sm text-ink-muted"><AlertCircle aria-hidden="true" className="h-6 w-6 text-danger" /><p>{error}</p></div>
          : previewUrl && <img alt={`Xem trước ${title}, trang ${pageIndex + 1}`} src={previewUrl} onError={() => setError("Không thể hiển thị trang xem trước. Bạn có thể tải tài liệu bên dưới.")} className="mx-auto h-auto w-full rounded-xl border border-hairline bg-white shadow-sm" />}
      </div>
      <footer className="shrink-0 border-t border-hairline bg-surface-panel px-4 py-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-medium text-ink"><FileText aria-hidden="true" className="h-3.5 w-3.5 text-report-brand-ink-strong" />Tải tài liệu</div>
        <div className="grid grid-cols-3 gap-2">
          {FORMATS.map((format) => {
            const artifact = job?.artifacts.find((item) => artifactFormat(item) === format);
            const downloading = artifact && downloadingId === artifact.report_id;
            return <button key={format} type="button" disabled={!artifact || !!downloadingId} onClick={() => artifact && void handleDownload(artifact)} aria-label={`Tải ${format.toUpperCase()}${artifact ? "" : " — chưa sẵn sàng"}`} className="vt-focus-visible flex min-w-0 flex-col items-center gap-1 rounded-lg border border-report-brand/25 bg-report-soft px-2 py-2.5 text-report-brand-ink-strong transition-colors duration-fast hover:bg-report-brand/12 disabled:cursor-not-allowed disabled:opacity-45">
              <span className="flex items-center gap-1.5 text-xs font-semibold">{downloading ? <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" /> : <Download aria-hidden="true" className="h-3.5 w-3.5" />}{format.toUpperCase()}</span>
              <span className="vt-num text-[10px] opacity-75">{artifact ? `${(artifact.size_bytes / 1024).toFixed(0)} KB` : "Chưa sẵn sàng"}</span>
            </button>;
          })}
        </div>
      </footer>
    </aside>
  );
}
