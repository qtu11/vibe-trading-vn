import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw, X } from "lucide-react";
import { authHeaders } from "@/lib/apiAuth";
import { ContextMemoryPanel, type ContextSnapshot, type ContextView } from "./ContextMemoryPanel";

function nonnegative(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

/** Context occupancy uses one prompt snapshot, never accumulated billed usage. */
export function ContextUsageIndicator({ sessionId, live, modelKey = "", compact = false }: {
  sessionId: string | null; live?: ContextSnapshot; modelKey?: string; compact?: boolean;
}) {
  const { i18n } = useTranslation(), vi = i18n.language.startsWith("vi");
  const l = (en: string, vn: string) => vi ? vn : en;
  const [open, setOpen] = useState(false), [hovered, setHovered] = useState(false);
  const [view, setView] = useState<ContextView | null>(null), [error, setError] = useState("");
  const [modelMetadata, setModelMetadata] = useState<ContextView["model_context"]>(null);
  const [loading, setLoading] = useState(false), [revision, setRevision] = useState(0);
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null);
  const popoverId = useId(), tooltipId = useId();
  useEffect(() => { setOpen(false); setHovered(false); setView(null); setModelMetadata(null); setError(""); }, [sessionId, modelKey]);
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
    const dismiss = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); setOpen(false); trigger.current?.focus(); setHovered(false); } };
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
  const remaining = knownWindow && contextWindow !== null && used !== null ? Math.max(0, contextWindow - used) : null;
  const compaction = snapshot?.compaction;
  const model = prompt?.model ?? metadata?.model ?? modelKey.slice(modelKey.indexOf(":") + 1);
  const n = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value) ? Math.round(value).toLocaleString(vi ? "vi-VN" : "en-US") : l("Unknown", "Chưa có dữ liệu");
  const compactLabel = compaction?.state === "running" ? l("Compacting context…", "Đang nén context…")
    : compaction?.state === "completed" ? l("Context compacted", "Đã nén context")
    : compaction?.state === "failed" ? l("Compaction degraded", "Nén context bị lỗi")
    : compaction?.state === "skipped" ? l("Compaction skipped", "Đã bỏ qua nén context")
    : compaction?.state === "idle" ? l("No compaction this run", "Lượt này chưa nén context")
    : metadata?.automatic_compaction === true ? l("Automatic compaction enabled", "Đã bật tự động nén context") : l("Compaction status unavailable", "Chưa có trạng thái nén context");
  const label = percentage === null ? l("Context usage unknown", "Chưa có mức sử dụng context") : l(`Context approximately ${percentage}% used`, `Context đã dùng khoảng ${percentage}%`);
  const stroke = ratio === null ? "text-muted-foreground/40" : ratio >= 0.9 ? "text-amber-500" : "text-muted-foreground";
  const showTooltip = hovered && !open;

  return <div ref={root} className="relative flex min-w-0 justify-end text-xs" data-context-usage>
    <button ref={trigger} type="button" aria-label={label} aria-haspopup="dialog" aria-expanded={open} aria-controls={popoverId}
      aria-describedby={showTooltip ? tooltipId : undefined}
      onClick={() => { setOpen((current) => !current); setHovered(false); }}
      onPointerEnter={() => setHovered(true)} onPointerLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)} onBlur={() => setHovered(false)}
      className="inline-flex min-h-8 min-w-8 items-center gap-1.5 rounded-md px-1.5 text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary motion-reduce:transition-none">
      <svg viewBox="0 0 20 20" className={`h-4 w-4 shrink-0 -rotate-90 ${stroke}`} aria-hidden="true">
        <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="2" className="opacity-20" />
        {ratio !== null && <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
          pathLength="100" strokeDasharray={`${Math.min(100, Math.max(0, ratio * 100))} 100`} />}
        {ratio === null && <circle cx="10" cy="10" r="1.3" fill="currentColor" />}
      </svg>
      {!compact && <span className="max-w-[15rem] truncate">{snapshot?.compaction?.state === "running" ? compactLabel : percentage === null ? l("Context", "Context") : `~${percentage}%`}</span>}
    </button>
    {showTooltip && <div id={tooltipId} role="tooltip" className="pointer-events-none absolute bottom-full end-0 z-50 mb-2 w-64 max-w-[calc(100vw-5rem)] rounded-lg border bg-popover p-3 text-popover-foreground shadow-lg">
      <p className="font-medium">{label}</p><p className="mt-1 text-muted-foreground">{l("Estimated prompt", "Prompt ước lượng")}: {n(used)} · {l("Remaining", "Còn lại")}: {n(remaining)}</p>
      <p className="text-muted-foreground">{l("Model window", "Cửa sổ model")}: {n(contextWindow)}{!knownWindow && contextWindow !== null ? ` · ${l("conservative budget", "giới hạn dự phòng")}` : ""}</p>
    </div>}
    {open && <section id={popoverId} role="dialog" aria-modal="false" aria-label={l("Context usage details", "Chi tiết sử dụng context")}
      className="absolute bottom-full end-0 z-50 mb-2 max-h-[min(70vh,38rem)] w-[23rem] max-w-[calc(100vw-5rem)] space-y-3 overflow-y-auto rounded-xl border bg-popover p-4 text-popover-foreground shadow-xl">
      <div className="flex items-start justify-between gap-3"><div><h2 className="font-semibold">{l("Context window", "Cửa sổ context")}</h2>
        <p className="mt-1 break-words text-muted-foreground">{model || l("Model metadata unavailable", "Chưa có thông tin model")}</p></div>
        <button type="button" aria-label={l("Close context details", "Đóng chi tiết context")} onClick={() => { setOpen(false); trigger.current?.focus(); setHovered(false); }} className="rounded p-1 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"><X size={14} aria-hidden="true" /></button></div>
      <p className="font-medium">{label}</p>
      <dl className="space-y-1.5">
        {[[l("Estimated prompt tokens", "Token prompt ước lượng"), n(used)], [l("Remaining tokens", "Token còn lại"), n(remaining)],
          [l("Model window", "Cửa sổ model"), n(contextWindow)], [l("Last provider input", "Input provider gần nhất"), n(prompt?.last_reported_input_tokens)],
          [l("Compaction threshold", "Ngưỡng nén context"), n(prompt?.compact_at ?? metadata?.compact_at)],
          [l("Prompt cost ceiling", "Trần độ dài prompt"), n(prompt?.prompt_cost_cap ?? metadata?.prompt_cost_cap)]].map(([key, value]) => <div key={key} className="flex flex-wrap justify-between gap-x-3"><dt className="text-muted-foreground">{key}</dt><dd className="font-mono tabular-nums">{value}</dd></div>)}
      </dl>
      {!knownWindow && contextWindow !== null && <p className="text-muted-foreground">{l("This is a conservative fallback budget; the model's actual window is unknown. No occupancy percentage is inferred.", "Đây là giới hạn dự phòng; chưa biết cửa sổ thực của model nên chưa tính phần trăm sử dụng.")}</p>}
      <p className="text-muted-foreground">{l("Prompt size is estimated at the snapshot. Last-request input and total billed tokens are separate measurements; long-term memory is stored separately.", "Độ dài prompt được ước lượng tại thời điểm ghi nhận. Input request gần nhất và tổng token đã dùng là các số khác nhau; bộ nhớ dài hạn được lưu riêng.")}</p>
      {prompt?.observed_at && <p className="break-all text-muted-foreground">{l("Snapshot", "Ghi nhận")}: {prompt.observed_at} · {prompt.phase}</p>}
      {source && <p className="break-all text-muted-foreground">{l("Window source", "Nguồn giới hạn")}: {source}</p>}
      {confidence && <p className="break-all text-muted-foreground">{l("Window confidence", "Độ xác nhận giới hạn")}: {confidence}</p>}
      <p role="status" className="flex items-center gap-1.5"><span className={`h-1.5 w-1.5 rounded-full ${compaction?.state === "running" ? "bg-primary motion-safe:animate-pulse" : "bg-muted-foreground/50"}`} />{compactLabel}
        {compaction?.automatic !== undefined && <span className="text-muted-foreground">· {compaction.automatic ? l("automatic", "tự động") : l("manual", "thủ công")}</span>}
        {compaction?.count !== undefined && <span className="text-muted-foreground">· {n(compaction.count)}</span>}</p>
      {!snapshot && view?.last_run && <p className="text-muted-foreground">{l("The prior run's context is available in diagnostics below; it is not the current model's occupancy.", "Context của lượt trước nằm trong phần chi tiết bên dưới, không phải mức sử dụng model hiện tại.")}</p>}
      {loading && <p role="status">{l("Reading context status…", "Đang đọc trạng thái context…")}</p>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <button type="button" disabled={loading} onClick={() => setRevision((current) => current + 1)} className="inline-flex items-center gap-1.5 rounded border px-2 py-1 hover:bg-muted disabled:opacity-50"><RefreshCw size={12} aria-hidden="true" />{l("Refresh metadata", "Làm mới thông tin")}</button>
      <ContextMemoryPanel key={sessionId || "draft"} sessionId={sessionId} live={snapshot} embedded />
    </section>}
  </div>;
}
