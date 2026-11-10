import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, ExternalLink, Globe, Loader2, RotateCw, X } from "lucide-react";
import type { SourceBrowserState } from "@/desktop";
import { useReportPreviewStore } from "@/stores/reportPreview";
import { evidenceUrl } from "@/lib/research";

/**
 * The source browser for one tab.
 *
 * The panel stays mounted while other tabs are shown, so the page the user
 * was reading is still open when they switch back.
 */
export function SourceBrowserPanel({ tabId, resizing = false }: { tabId?: string; resizing?: boolean }) {
  const tab = useReportPreviewStore((state) => state.tabs.find((item) => item.id === (tabId ?? state.activeId)) ?? null);
  const selection = tab && tab.kind === "source" && tab.selection.kind === "source" ? tab.selection : null;
  const active = useReportPreviewStore((state) => state.activeId === tab?.id);
  const closeTab = useReportPreviewStore((state) => state.closeTab);
  const viewport = useRef<HTMLDivElement>(null), closeRef = useRef<HTMLButtonElement>(null);
  const [state, setState] = useState<SourceBrowserState | null>(null);
  const lastState = useRef<SourceBrowserState | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const browser = window.vibeDesktop?.sourceBrowser;
  const titleId = useId();

  useEffect(() => { setState(null); lastState.current = null; }, [selection]);

  useEffect(() => {
    if (!selection || tabId) return;
    const previous = document.activeElement;
    closeRef.current?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault(); event.stopImmediatePropagation(); closeTab(tab!.id);
    };
    document.addEventListener("keydown", escape, true);
    return () => {
      document.removeEventListener("keydown", escape, true);
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, [selection, tab, tabId, closeTab]);

  useEffect(() => {
    if (!selection || !browser || !viewport.current || !active) return;
    let mounted = true;
    const bounds = () => {
      const rect = viewport.current!.getBoundingClientRect();
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
    };
    const unsubscribe = browser.onState((next) => {
      if (!mounted) return;
      if (next.closed) closeTab(tab!.id);
      else { lastState.current = next; setState(next); }
    });
    // shortcut: the native bridge owns one view; restore each tab's last safe URL, upgrade the bridge for independent navigation history.
    const url = evidenceUrl(lastState.current?.url) || selection.sourceUrl;
    void browser.open(url, bounds()).catch(() => {
      if (mounted) setState({ url, title: selection.title, loading: false, canGoBack: false, canGoForward: false, error: "Không thể mở nguồn. Hãy thử tải lại." });
    });
    return () => { mounted = false; unsubscribe(); browser.close(); };
  }, [selection, browser, tab, active, closeTab]);

  useLayoutEffect(() => {
    if (!selection || !browser || !viewport.current || !active) return;
    const resize = () => {
      const { x, y, width, height } = viewport.current!.getBoundingClientRect();
      // Native views sit above DOM pointer capture, so hide the view while the divider moves.
      browser.setBounds({ x, y, width: resizing ? 0 : width, height: resizing ? 0 : height });
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(viewport.current);
    window.addEventListener("resize", resize);
    return () => { observer.disconnect(); window.removeEventListener("resize", resize); };
  }, [selection, browser, active, resizing]);

  if (!selection) return null;
  const url = state?.url || selection.sourceUrl;
  const buttonClass = "rounded-md p-2 hover:bg-muted disabled:opacity-35 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary";
  return <aside aria-labelledby={titleId} className="flex h-full min-h-0 w-full flex-col bg-background">
    <header className="flex items-center gap-2 border-b border-border px-3 py-2">
      <Globe aria-hidden="true" className="h-4 w-4 shrink-0 text-primary" />
      <h2 id={titleId} className="min-w-0 flex-1 truncate text-sm font-semibold">{state?.title || selection.title}</h2>
      <button ref={closeRef} type="button" aria-label="Đóng trình duyệt nguồn" className={buttonClass} onClick={() => closeTab(tab!.id)}><X aria-hidden="true" className="h-4 w-4" /></button>
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
