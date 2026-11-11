import { useEffect, useId, useRef, useState } from "react";
import { FileText, Globe, Search, X } from "lucide-react";
import { ReportPreviewPanel } from "./ReportPreviewPanel";
import { SourceBrowserPanel } from "./SourceBrowserPanel";
import { ResearchPreviewPanel } from "./ResearchPreviewPanel";
import { safeGet, safeSet } from "@/lib/storage";
import { cn } from "@/lib/utils";
import { useReportPreviewStore, type PreviewTab } from "@/stores/reportPreview";

const WIDTH_KEY = "qa-preview-width";
const DEFAULT_WIDTH = 48;
const MIN_WIDTH = 30;
const MAX_WIDTH = 70;

/** A stored width is only trusted when it is a usable number in range. */
function storedWidth(): number {
  const value = Number.parseFloat(safeGet(WIDTH_KEY) ?? "");
  return Number.isFinite(value) && value >= MIN_WIDTH && value <= MAX_WIDTH ? value : DEFAULT_WIDTH;
}

/**
 * The research browser column.
 *
 * Layout: a sticky tab strip on top of a single active viewport. The strip is
 * a proper tablist with roving focus; the viewport hosts one mounted panel per
 * tab so a loaded document or in-flight web view survives a tab switch.
 */
export function PreviewPane() {
  const tabs = useReportPreviewStore((state) => state.tabs);
  const activeId = useReportPreviewStore((state) => state.activeId);
  const setActive = useReportPreviewStore((state) => state.setActive);
  const closeTab = useReportPreviewStore((state) => state.closeTab);
  const close = useReportPreviewStore((state) => state.close);
  const stripRef = useRef<HTMLDivElement>(null);
  const paneRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(storedWidth);
  const widthRef = useRef(width);
  const [dragging, setDragging] = useState(false);
  const id = useId();
  const open = tabs.length > 0;

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement;
    stripRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const active = useReportPreviewStore.getState().activeId;
      if (!active) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      closeTab(active);
    };
    document.addEventListener("keydown", escape, true);
    return () => {
      document.removeEventListener("keydown", escape, true);
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, [open, closeTab]);

  useEffect(() => {
    const selected = stripRef.current?.querySelector<HTMLElement>('[aria-selected="true"]');
    selected?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    if (document.activeElement === document.body || stripRef.current?.contains(document.activeElement)) selected?.focus();
  }, [activeId]);

  const resize = (value: number) => {
    const next = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, value));
    widthRef.current = next;
    setWidth(next);
  };
  const persistWidth = () => safeSet(WIDTH_KEY, String(Math.round(widthRef.current * 10) / 10));
  const resizeToPointer = (clientX: number) => {
    const bounds = paneRef.current?.parentElement?.getBoundingClientRect();
    if (bounds?.width) resize((bounds.right - clientX) / bounds.width * 100);
  };
  const stopDragging = () => {
    setDragging(false);
    persistWidth();
  };

  if (tabs.length === 0) return null;

  return (
    <div
      ref={paneRef}
      style={{ width: `${width}%` }}
      className="relative z-20 flex h-full min-h-0 min-w-[20rem] shrink-0 flex-col border-l border-hairline bg-surface-base lg:max-w-[calc(100%_-_20rem)] max-lg:absolute max-lg:inset-0 max-lg:!w-full max-lg:min-w-0 max-lg:max-w-none"
    >
      <div
        role="separator"
        tabIndex={0}
        title="Kéo để đổi độ rộng · nhấp đúp để đặt lại"
        aria-label="Điều chỉnh độ rộng khung xem trước"
        aria-orientation="vertical"
        aria-controls={`${id}-content`}
        aria-valuemin={MIN_WIDTH}
        aria-valuemax={MAX_WIDTH}
        aria-valuenow={Math.round(width)}
        aria-valuetext={`Khung xem trước ${Math.round(width)}%`}
        className="group absolute inset-y-0 -left-1.5 z-30 flex w-3 touch-none cursor-col-resize items-center justify-center transition-colors duration-fast hover:bg-accent/10 focus-visible:bg-accent/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent max-lg:hidden"
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.preventDefault();
          event.currentTarget.setPointerCapture(event.pointerId);
          setDragging(true);
        }}
        onPointerMove={(event) => { if (dragging) resizeToPointer(event.clientX); }}
        onPointerUp={(event) => {
          stopDragging();
          if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onPointerCancel={stopDragging}
        onLostPointerCapture={() => setDragging(false)}
        onDoubleClick={() => { resize(DEFAULT_WIDTH); persistWidth(); }}
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          resize(event.key === "Home" ? MIN_WIDTH : event.key === "End" ? MAX_WIDTH : widthRef.current + (event.key === "ArrowLeft" ? 5 : -5));
          persistWidth();
        }}
      >
        <span
          aria-hidden="true"
          className={cn(
            "pointer-events-none h-10 w-[3px] rounded-full bg-hairline-strong transition-colors duration-fast",
            "group-hover:bg-accent group-focus-visible:bg-accent",
            dragging && "bg-accent",
          )}
        />
      </div>

      {/* Tab strip */}
      <div
        ref={stripRef}
        role="tablist"
        aria-label="Bản xem trước đang mở"
        className="flex w-full shrink-0 items-end gap-1 overflow-x-auto border-b border-hairline bg-surface-sidebar px-2 pt-1.5"
        onKeyDown={(event) => {
          if (!(event.target instanceof HTMLElement) || event.target.getAttribute("role") !== "tab") return;
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const index = tabs.findIndex((tab) => tab.id === activeId);
          const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
          setActive(tabs[next].id);
          stripRef.current?.querySelectorAll<HTMLElement>('[role="tab"]')[next]?.focus();
        }}
      >
        {tabs.map((tab) => (
          <TabButton key={tab.id} id={`${id}-${encodeURIComponent(tab.id)}`} tab={tab} active={tab.id === activeId} onSelect={() => setActive(tab.id)} onClose={() => closeTab(tab.id)} />
        ))}
        <button
          type="button"
          aria-label="Đóng tất cả bản xem trước"
          onClick={close}
          className="vt-focus-visible mb-1 ml-auto shrink-0 rounded-md p-1.5 text-ink-faint transition-colors duration-fast hover:bg-muted hover:text-ink"
        >
          <X aria-hidden="true" className="h-3.5 w-3.5" />
        </button>
      </div>

      <div id={`${id}-content`} className={cn("flex min-h-0 w-full flex-1 flex-col", dragging && "pointer-events-none select-none")}>
        {tabs.map((tab) => (
          <TabContent key={tab.id} id={`${id}-${encodeURIComponent(tab.id)}`} tab={tab} active={tab.id === activeId} resizing={dragging} />
        ))}
      </div>
    </div>
  );
}

const TAB_ICON = { report: FileText, source: Globe, research: Search } as const;

function TabButton({ id, tab, active, onSelect, onClose }: { id: string; tab: PreviewTab; active: boolean; onSelect: () => void; onClose: () => void }) {
  const Icon = TAB_ICON[tab.kind];
  return (
    <div
      title={tab.title}
      className={cn(
        "group relative flex max-w-[14rem] shrink-0 items-center gap-1.5 rounded-t-md border border-b-0 px-2.5 py-1.5 text-xs transition-colors duration-fast",
        active
          ? "border-hairline bg-surface-base font-medium text-ink"
          : "border-transparent text-ink-muted hover:bg-muted/60 hover:text-ink-secondary",
      )}
    >
      {active && (
        <span aria-hidden="true" className="absolute inset-x-0 -bottom-px h-[2px] rounded-full bg-accent" />
      )}
      <button
        id={`${id}-tab`}
        role="tab"
        aria-selected={active}
        aria-controls={`${id}-panel`}
        tabIndex={active ? 0 : -1}
        type="button"
        onClick={onSelect}
        className="vt-focus-visible flex min-w-0 flex-1 items-center gap-1.5 text-left"
      >
        <Icon aria-hidden="true" className={cn("h-3.5 w-3.5 shrink-0", active ? "text-accent-ink" : "text-ink-faint")} />
        <span className="truncate">{tab.title}</span>
      </button>
      <button
        type="button"
        aria-label={`Đóng ${tab.title}`}
        onClick={(event) => {
          // The close button sits inside the tab, so a click there must not
          // also activate the tab it closes.
          event.stopPropagation();
          onClose();
        }}
        className={cn(
          "vt-focus-visible shrink-0 rounded p-0.5 text-ink-faint transition-opacity duration-fast hover:bg-muted hover:text-ink",
          active ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
        )}
      >
        <X aria-hidden="true" className="h-3 w-3" />
      </button>
    </div>
  );
}

/**
 * Every open preview stays mounted; only the inactive ones are hidden.
 * `hidden` keeps the DOM and the component state, so a loaded document and
 * an in-flight request survive a tab switch.
 */
function TabContent({ id, tab, active, resizing }: { id: string; tab: PreviewTab; active: boolean; resizing: boolean }) {
  return (
    <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-tab`} hidden={!active} className={active ? "flex h-full min-h-0 w-full flex-col" : "hidden"}>
      {tab.kind === "source" && <SourceBrowserPanel tabId={tab.id} resizing={resizing} />}
      {tab.kind === "research" && <ResearchPreviewPanel tabId={tab.id} />}
      {tab.kind === "report" && <ReportPreviewPanel tabId={tab.id} />}
    </div>
  );
}
