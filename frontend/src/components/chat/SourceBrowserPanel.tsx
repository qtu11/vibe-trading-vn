import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, ExternalLink, Globe, Loader2, RotateCw, X } from "lucide-react";
import type { SourceBrowserState } from "@/desktop";
import { useReportPreviewStore } from "@/stores/reportPreview";

export function SourceBrowserPanel() {
  const selected = useReportPreviewStore((state) => state.selection);
  const selection = selected && "sourceUrl" in selected ? selected : null;
  const close = useReportPreviewStore((state) => state.close);
  const viewport = useRef<HTMLDivElement>(null), closeRef = useRef<HTMLButtonElement>(null);
  const [state, setState] = useState<SourceBrowserState | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const browser = window.vibeDesktop?.sourceBrowser;

  useEffect(() => {
    if (!selection) return;
    setState(null);
    const previous = document.activeElement;
    closeRef.current?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault(); event.stopImmediatePropagation(); close();
    };
    document.addEventListener("keydown", escape, true);
    return () => {
      document.removeEventListener("keydown", escape, true);
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, [selection, close]);

  useEffect(() => {
    if (!selection || !browser || !viewport.current) return;
    let active = true;
    const bounds = () => {
      const rect = viewport.current!.getBoundingClientRect();
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
    };
    const unsubscribe = browser.onState((next) => { if (active) { if (next.closed) close(); else setState(next); } });
    void browser.open(selection.sourceUrl, bounds()).catch(() => {
      if (active) setState({ url: selection.sourceUrl, title: selection.title, loading: false, canGoBack: false, canGoForward: false, error: "Không thể mở nguồn. Hãy thử tải lại." });
    });
    const resize = () => browser.setBounds(bounds());
    const observer = new ResizeObserver(resize);
    observer.observe(viewport.current);
    window.addEventListener("resize", resize);
    return () => { active = false; observer.disconnect(); window.removeEventListener("resize", resize); unsubscribe(); browser.close(); };
  }, [selection, browser, close]);

  if (!selection) return null;
  const url = state?.url || selection.sourceUrl;
  const buttonClass = "rounded-md p-2 hover:bg-muted disabled:opacity-35 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary";
  return <aside aria-labelledby="source-browser-title" className="z-20 flex h-full w-[48%] min-w-[22rem] max-w-3xl shrink-0 flex-col border-l border-border bg-background max-lg:absolute max-lg:inset-0 max-lg:w-full max-lg:min-w-0 max-lg:max-w-none">
    <header className="flex items-center gap-2 border-b border-border px-3 py-2">
      <Globe aria-hidden="true" className="h-4 w-4 shrink-0 text-primary" />
      <h2 id="source-browser-title" className="min-w-0 flex-1 truncate text-sm font-semibold">{state?.title || selection.title}</h2>
      <button ref={closeRef} type="button" aria-label="Đóng trình duyệt nguồn" className={buttonClass} onClick={close}><X aria-hidden="true" className="h-4 w-4" /></button>
    </header>
    <nav aria-label="Trình duyệt nguồn" className="flex items-center gap-1 border-b border-border p-2">
      {browser && <>
        <button type="button" aria-label="Quay lại" disabled={!state?.canGoBack} className={buttonClass} onClick={() => browser.navigate("back")}><ArrowLeft aria-hidden="true" className="h-4 w-4" /></button>
        <button type="button" aria-label="Tiến tới" disabled={!state?.canGoForward} className={buttonClass} onClick={() => browser.navigate("forward")}><ArrowRight aria-hidden="true" className="h-4 w-4" /></button>
      </>}
      <button type="button" aria-label="Tải lại nguồn" className={buttonClass} onClick={() => { if (browser) browser.navigate("reload"); else setReloadKey((key) => key + 1); }}><RotateCw aria-hidden="true" className="h-4 w-4" /></button>
      <span className="min-w-0 flex-1 truncate rounded border border-border bg-muted/40 px-2 py-1.5 text-xs text-muted-foreground" title={url}>{url}</span>
      <a href={url} target="_blank" rel="noopener noreferrer" aria-label="Mở nguồn bằng trình duyệt ngoài" className={buttonClass} onClick={browser ? (event) => { event.preventDefault(); browser.openExternal(url); } : undefined}><ExternalLink aria-hidden="true" className="h-4 w-4" /></a>
    </nav>
    {!browser && <p className="border-b border-border px-3 py-2 text-xs text-muted-foreground">Một số website chặn xem nhúng trên bản web. Dùng ứng dụng desktop để đọc trong khung này, hoặc chọn mở bằng trình duyệt ngoài.</p>}
    {state?.loading && <p role="status" className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground"><Loader2 aria-hidden="true" className="h-3 w-3 animate-spin" />Đang tải nguồn…</p>}
    {state?.error && <p role="alert" className="px-3 py-2 text-sm text-danger">{state.error}</p>}
    <div ref={viewport} className="min-h-0 flex-1 bg-white">
      {!browser && <iframe key={`${selection.sourceUrl}:${reloadKey}`} title={`Nguồn: ${selection.title}`} src={selection.sourceUrl} sandbox="allow-scripts allow-forms" referrerPolicy="no-referrer" className="h-full w-full border-0" />}
    </div>
  </aside>;
}
