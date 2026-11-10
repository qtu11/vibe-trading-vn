import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, Gauge, RefreshCw, X } from "lucide-react";
import { authHeaders } from "@/lib/apiAuth";
import { ContextMemoryPanel, type ContextSnapshot, type ContextView } from "./ContextMemoryPanel";
import "./ContextUsageIndicator.css";

function nonnegative(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

/** Compact token counts in the same shape as Codex: 196k / 475k. */
function compactTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (value >= 1_000) {
    const thousands = value / 1_000;
    return `${thousands >= 100 || Number.isInteger(thousands) ? Math.round(thousands) : thousands.toFixed(1).replace(/\.0$/, "")}k`;
  }
  return String(Math.round(value));
}

/** Context occupancy uses one prompt snapshot, never accumulated billed usage. */
export function ContextUsageIndicator({ sessionId, live, modelKey = "", compact = false }: {
  sessionId: string | null; live?: ContextSnapshot; modelKey?: string; compact?: boolean;
}) {
  const { i18n } = useTranslation(), vi = i18n.language.startsWith("vi");
  const l = (en: string, vn: string) => vi ? vn : en;
  const [open, setOpen] = useState(false), [hovered, setHovered] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [view, setView] = useState<ContextView | null>(null), [error, setError] = useState("");
  const [modelMetadata, setModelMetadata] = useState<ContextView["model_context"]>(null);
  const [loading, setLoading] = useState(false), [revision, setRevision] = useState(0);
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null);
  const popoverId = useId(), tooltipId = useId(), detailsId = useId();
  const close = () => { setOpen(false); setShowDetails(false); setHovered(false); };
  useEffect(() => { close(); setView(null); setModelMetadata(null); setError(""); }, [sessionId, modelKey]);
  useEffect(() => {
    let active = true;
    const controller = new AbortController(); setLoading(true); setError("");
    async function read(url: string) {
      const response = await fetch(url, { headers: authHeaders(), signal: controller.signal });
      if (!response.ok) throw new Error(l("Cannot read context status", "Không đọc được trạng thái context"));
      return response.json();
    }
    async function load() {
      try {
        const value = await read(`/settings/llm/context${revision ? "?refresh=true" : ""}`);
        if (typeof value?.model !== "string" || typeof value?.source !== "string" || !Number.isFinite(value?.window) || value.window <= 0) throw new Error(l("Invalid model metadata", "Thông tin model không hợp lệ"));
        if (active) setModelMetadata(value);
      } catch (reason) {
        if (active && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : l("Cannot read context status", "Không đọc được trạng thái context"));
      }
      if (!active || controller.signal.aborted) return;
      if (sessionId) {
        try {
          const value = await read(`/sessions/${encodeURIComponent(sessionId)}/context`);
          if (value?.version !== 1 || value.session_id !== sessionId) throw new Error(l("Invalid context response", "Phản hồi context không hợp lệ"));
          if (active) setView(value);
        } catch (reason) {
          if (active && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : l("Cannot read context status", "Không đọc được trạng thái context"));
        }
      }
      if (active) setLoading(false);
    }
    void load();
    return () => { active = false; controller.abort(); };
  }, [sessionId, modelKey, revision, vi]);
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) close(); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); close(); trigger.current?.focus(); } };
    document.addEventListener("pointerdown", dismiss); document.addEventListener("keydown", escape, true);
    return () => { document.removeEventListener("pointerdown", dismiss); document.removeEventListener("keydown", escape, true); };
  }, [open]);

  // last_run is historical diagnostics. It must not supply a current ratio
  // after a reload, conversation switch, or model change.
  const [selectedProvider, ...selectedModelParts] = modelKey.split(":"), selectedModel = selectedModelParts.join(":");
  const matchesModel = (value: ContextSnapshot | null | undefined) => !modelKey || !value?.current_prompt
    || ((!value.current_prompt.model || value.current_prompt.model === selectedModel)
      && (!value.current_prompt.provider || value.current_prompt.provider === selectedProvider));
  const snapshot = live && (!live.session_id || live.session_id === sessionId) && matchesModel(live)
    ? live : matchesModel(view?.current_context) ? view?.current_context ?? undefined : undefined;
  const prompt = snapshot?.current_prompt;
  const metadata = modelMetadata ?? view?.model_context;
  const contextWindow = nonnegative(prompt?.model_window ?? metadata?.window);
  const source = prompt?.window_source ?? metadata?.source;
  const confidence = prompt?.window_confidence ?? metadata?.confidence;
  const used = nonnegative(prompt?.estimated_next_request_tokens);
  const knownWindow = contextWindow !== null && contextWindow > 0 && source !== "default"
    && ["operator_override", "provider_error", "provider_reported", "catalog"].includes(confidence ?? "");
  const ratio = knownWindow && contextWindow !== null && used !== null ? used / contextWindow : null;
  const percentage = ratio === null ? null : Math.round(ratio * 100);
  const barWidth = percentage === null ? 0 : Math.min(100, Math.max(0, percentage));
  const remainingPercentage = percentage === null ? null : Math.max(0, 100 - percentage);
  const remaining = knownWindow && contextWindow !== null && used !== null ? Math.max(0, contextWindow - used) : null;
  const compaction = snapshot?.compaction;
  const model = prompt?.model ?? metadata?.model ?? modelKey.slice(modelKey.indexOf(":") + 1);
  const unknown = l("Unknown", "Chưa có dữ liệu");
  const n = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value) ? Math.round(value).toLocaleString(vi ? "vi-VN" : "en-US") : unknown;
  const compactLabel = compaction?.state === "running" ? l("Compacting context…", "Đang nén context…")
    : compaction?.state === "completed" ? l("Context compacted", "Đã nén context")
    : compaction?.state === "failed" ? l("Compaction degraded", "Nén context bị lỗi")
    : compaction?.state === "skipped" ? l("Compaction skipped", "Đã bỏ qua nén context")
    : compaction?.state === "idle" ? l("No compaction this run", "Lượt này chưa nén context")
    : metadata?.automatic_compaction === true ? l("Automatic compaction enabled", "Đã bật tự động nén context") : l("Compaction status unavailable", "Chưa có trạng thái nén context");
  const label = percentage === null ? l("Context usage unknown", "Chưa có mức sử dụng context") : l(`Context approximately ${percentage}% used`, `Context đã dùng khoảng ${percentage}%`);
  const usageLine = used === null ? l("No token estimate for this snapshot", "Chưa có ước lượng token cho lần ghi nhận này")
    : knownWindow && contextWindow !== null ? l(`${compactTokens(used)} / ${compactTokens(contextWindow)} tokens used`, `${compactTokens(used)} / ${compactTokens(contextWindow)} token được sử dụng`)
    : contextWindow !== null ? l(`~${compactTokens(used)} tokens estimated · ${compactTokens(contextWindow)} fallback window`, `~${compactTokens(used)} token ước lượng · cửa sổ ${compactTokens(contextWindow)} dự phòng`)
    : l(`~${compactTokens(used)} tokens estimated`, `~${compactTokens(used)} token ước lượng`);
  const tone = ratio === null ? "text-muted-foreground/40" : ratio >= 0.9 ? "text-rose-500 dark:text-rose-400" : ratio >= 0.75 ? "text-amber-500 dark:text-amber-400" : "text-foreground/70";
  const barTone = ratio === null ? "bg-muted-foreground/25" : ratio >= 0.9 ? "bg-rose-500" : ratio >= 0.75 ? "bg-amber-500" : "bg-foreground/80";
  const showTooltip = hovered && !open;
  const closeAndFocus = () => { close(); trigger.current?.focus(); };

  return <div ref={root} className="relative flex min-w-0 justify-end text-xs" data-context-usage>
    <button ref={trigger} type="button" aria-label={label} aria-haspopup="dialog" aria-expanded={open} aria-controls={popoverId}
      aria-describedby={showTooltip ? tooltipId : undefined}
      onClick={() => { if (open) close(); else { setOpen(true); setHovered(false); } }}
      onPointerEnter={() => setHovered(true)} onPointerLeave={() => setHovered(false)}
      className={`group inline-flex h-[30px] items-center gap-1.5 rounded-full ${compact ? "px-2.5" : "px-3"} text-[12px] font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/60 motion-reduce:transition-none ${
        open
          ? "border border-primary/40 bg-primary/10 text-primary shadow-xs"
          : "border border-zinc-200/80 dark:border-zinc-800/80 bg-zinc-100/60 dark:bg-zinc-900/60 hover:bg-zinc-200/60 dark:hover:bg-zinc-800/80 hover:border-zinc-300 dark:hover:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 shadow-2xs"
      }`}>
      <svg viewBox="0 0 24 24" className={`h-4 w-4 shrink-0 -rotate-90 ${tone}`} aria-hidden="true">
        <defs>
          <linearGradient id="ctx-grad-normal" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#10b981" />
            <stop offset="100%" stopColor="#06b6d4" />
          </linearGradient>
          <linearGradient id="ctx-grad-warn" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#f59e0b" />
            <stop offset="100%" stopColor="#d97706" />
          </linearGradient>
          <linearGradient id="ctx-grad-danger" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#ef4444" />
            <stop offset="100%" stopColor="#dc2626" />
          </linearGradient>
        </defs>
        <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="2.2" className="text-zinc-300 dark:text-zinc-700/60 opacity-30" />
        {ratio !== null && (
          <circle cx="12" cy="12" r="8.5" fill="none"
            stroke={ratio >= 0.9 ? "url(#ctx-grad-danger)" : ratio >= 0.75 ? "url(#ctx-grad-warn)" : "url(#ctx-grad-normal)"}
            strokeWidth="2.5" strokeLinecap="round"
            pathLength="100" strokeDasharray={`${Math.min(100, Math.max(0, ratio * 100))} 100`}
            className="transition-[stroke-dasharray] duration-500 ease-out motion-reduce:transition-none" />
        )}
        {ratio === null && (
          <circle cx="12" cy="12" r="1.8" fill="currentColor" className="text-zinc-400 dark:text-zinc-500 opacity-60" />
        )}
      </svg>
      <span className="text-[11.5px] font-medium tracking-tight">Context</span>
      {percentage !== null && <span className="text-[11px] font-semibold tabular-nums text-foreground/90">{percentage}%</span>}
    </button>
    {showTooltip && <div id={tooltipId} role="tooltip" className="pointer-events-none absolute bottom-full end-0 z-50 mb-2 w-64 max-w-[calc(100vw-5rem)] rounded-xl border border-border/70 bg-popover/95 p-3 text-popover-foreground shadow-xl backdrop-blur-xl">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-medium text-muted-foreground">{l("Context window", "Cửa sổ ngữ cảnh")}</p>
        <p className="text-xs font-semibold tabular-nums">{percentage === null ? "—" : `${percentage}%`}</p>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"><div className={`h-full rounded-full ${barTone}`} style={{ width: `${barWidth}%` }} /></div>
      <p className="mt-2 text-[11px] tabular-nums text-muted-foreground">{usageLine}</p>
      <p className="mt-0.5 text-[11px] text-muted-foreground">{percentage === null ? l("Usage unavailable", "Chưa có mức sử dụng context") : l(`Used ${percentage}% · ${remainingPercentage}% remaining`, `Đã sử dụng ${percentage}% · còn lại ${remainingPercentage}%`)}</p>
    </div>}
    {open && <section id={popoverId} role="dialog" aria-modal="false" aria-label={l("Context usage details", "Chi tiết sử dụng context")}
      className="absolute bottom-full end-0 z-50 mb-2 max-h-[min(72vh,40rem)] w-[23rem] max-w-[calc(100vw-5rem)] overflow-y-auto rounded-2xl border border-border/70 bg-popover/95 p-4 text-popover-foreground shadow-2xl backdrop-blur-xl">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted/70 text-muted-foreground"><Gauge size={16} aria-hidden="true" /></span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold tracking-tight">{l("Context window", "Cửa sổ ngữ cảnh")}</h2>
            <p className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className="truncate">{model || l("Model metadata unavailable", "Chưa có thông tin model")}</span>
              {prompt?.phase === "session_preview" && <span className="shrink-0 rounded-full bg-muted px-1.5 py-px text-[9px] font-medium uppercase tracking-wide">{l("preview", "dự kiến")}</span>}
            </p>
          </div>
        </div>
        <button type="button" aria-label={l("Close context details", "Đóng chi tiết context")} onClick={closeAndFocus} className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"><X size={14} aria-hidden="true" /></button>
      </div>

      <div className="mt-3 rounded-xl border border-border/60 bg-muted/25 p-3.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground">{l("Used", "Đã sử dụng")}</p>
            <p className="mt-0.5 text-3xl font-semibold leading-none tracking-tight tabular-nums">{percentage === null ? "—" : `${percentage}%`}</p>
          </div>
          {remainingPercentage !== null && <span className="mt-0.5 shrink-0 rounded-full border border-border/60 bg-background/60 px-2 py-0.5 text-[10px] font-medium tabular-nums text-muted-foreground">{l(`${remainingPercentage}% left`, `Còn lại ${remainingPercentage}%`)}</span>}
        </div>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted"><div className={`h-full rounded-full transition-[width] duration-500 motion-reduce:transition-none ${barTone}`} style={{ width: `${barWidth}%` }} /></div>
        <p className="mt-2 text-[11px] tabular-nums text-muted-foreground">{usageLine}</p>
        {percentage === null && <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
          {prompt ? l("The model window is not verified, so no percentage is inferred.", "Chưa xác định được cửa sổ model nên chưa suy ra phần trăm.")
            : l("Usage appears after a run reports its context snapshot.", "Mức sử dụng sẽ hiện sau khi lượt chạy gửi số liệu context.")}
        </p>}
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-2">
        {[[l("Estimated prompt", "Prompt ước lượng"), n(used)],
          [l("Last provider input", "Input provider gần nhất"), n(prompt?.last_reported_input_tokens)],
          [l("Model window", "Cửa sổ model"), n(contextWindow)],
          [l("Remaining tokens", "Token còn lại"), n(remaining)],
          [l("Compaction threshold", "Ngưỡng nén context"), n(prompt?.compact_at ?? metadata?.compact_at)],
          [l("Prompt ceiling", "Trần prompt"), n(prompt?.prompt_cost_cap ?? metadata?.prompt_cost_cap)]].map(([key, value]) =>
          <div key={key} className="min-w-0 rounded-lg border border-border/50 bg-background/40 px-2.5 py-2">
            <dt className="truncate text-[10px] text-muted-foreground">{key}</dt>
            <dd className={`mt-0.5 truncate text-[11px] font-medium ${value === unknown ? "text-muted-foreground" : "font-mono tabular-nums"}`} title={value}>{value}</dd>
          </div>)}
      </dl>

      <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-border/50 bg-background/40 px-3 py-2">
        <p className="flex min-w-0 items-center gap-2 text-[11px]">
          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${compaction?.state === "running" ? "bg-primary motion-safe:animate-pulse" : "bg-muted-foreground/50"}`} />
          <span className="truncate">{compactLabel}</span>
        </p>
        {(compaction?.automatic !== undefined || compaction?.count !== undefined) && <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
          {compaction?.automatic !== undefined && (compaction.automatic ? l("automatic", "tự động") : l("manual", "thủ công"))}
          {compaction?.count !== undefined && ` · ${n(compaction.count)}`}
        </span>}
      </div>

      {!knownWindow && contextWindow !== null && <p className="mt-2 rounded-lg border border-amber-500/20 bg-amber-500/[0.07] px-3 py-2 text-[11px] leading-relaxed text-amber-700 dark:text-amber-300">{l("This is a conservative fallback budget; the model's actual window is unknown, so no occupancy percentage is inferred.", "Đây là giới hạn dự phòng; chưa biết cửa sổ thực của model nên chưa tính phần trăm sử dụng.")}</p>}
      <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">{l("Prompt size is estimated at the snapshot. Last-request input and total billed tokens are separate measurements; long-term memory is stored separately.", "Độ dài prompt được ước lượng tại thời điểm ghi nhận. Input request gần nhất và tổng token đã dùng là các số khác nhau; bộ nhớ dài hạn được lưu riêng.")}</p>
      {!snapshot && view?.last_run && <p className="mt-2 text-[10px] text-muted-foreground">{l("The prior run's context is available in diagnostics below; it is not the current model's occupancy.", "Context của lượt trước nằm trong phần chi tiết bên dưới, không phải mức sử dụng model hiện tại.")}</p>}
      {loading && <p role="status" className="mt-2 text-[11px] text-muted-foreground">{l("Reading context status…", "Đang đọc trạng thái context…")}</p>}
      {error && <p role="alert" className="mt-2 text-[11px] text-destructive">{error}</p>}

      <div className="mt-3 flex items-center justify-between gap-2 border-t border-border/60 pt-3">
        <button type="button" disabled={loading} aria-label={l("Refresh metadata", "Làm mới thông tin")} onClick={() => setRevision((current) => current + 1)}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50">
          <RefreshCw size={12} aria-hidden="true" className={loading ? "motion-safe:animate-spin" : ""} />{l("Refresh", "Làm mới")}
        </button>
        <button type="button" aria-expanded={showDetails} aria-controls={detailsId} onClick={() => setShowDetails((current) => !current)}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
          {l("Details", "Chi tiết")}<ChevronDown size={12} aria-hidden="true" className={`transition-transform motion-reduce:transition-none ${showDetails ? "rotate-180" : ""}`} />
        </button>
      </div>
      {showDetails && <div id={detailsId} className="mt-3 space-y-2 border-t border-border/60 pt-3 text-[11px]">
        {prompt?.observed_at && <p className="break-all text-muted-foreground">{l("Snapshot", "Ghi nhận")}: {prompt.observed_at} · {prompt.phase}</p>}
        {source && <p className="break-all text-muted-foreground">{l("Window source", "Nguồn giới hạn")}: {source}</p>}
        {confidence && <p className="break-all text-muted-foreground">{l("Window confidence", "Độ xác nhận giới hạn")}: {confidence}</p>}
        <ContextMemoryPanel key={sessionId || "draft"} sessionId={sessionId} live={snapshot} embedded />
      </div>}
    </section>}
  </div>;
}
