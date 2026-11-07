import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, RotateCcw, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, type LLMSettings } from "@/lib/api";
import { effortLabelKey } from "@/lib/reasoningEffort";
import "./ComposerModelControls.css";

export function ComposerModelControls({ settings, disabled, onChange }: {
  settings: LLMSettings | null; disabled: boolean; onChange: (settings: LLMSettings) => void;
}) {
  const { t, i18n } = useTranslation(), vi = i18n.language.startsWith("vi");
  const [open, setOpen] = useState(false), [saving, setSaving] = useState(false);
  const [pickingModel, setPickingModel] = useState(false);
  const [model, setModel] = useState(""), [effort, setEffort] = useState("");
  const [models, setModels] = useState<string[]>([]), [error, setError] = useState("");
  const [modelEfforts, setModelEfforts] = useState<Record<string, string[]> | null>(null);
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null);
  const slider = useRef<HTMLInputElement>(null), dialogId = useId();
  const provider = settings?.providers.find((p) => p.name === settings.provider);
  const levels = settings?.provider === "custom" ? [] : modelEfforts?.[model] ?? provider?.reasoning_efforts ?? [];
  const steps = ["", ...levels];
  const label = (level: string) => effortLabelKey(level) ? t(effortLabelKey(level)!) : level || t("settings.providerDefault");
  const activeLevel = Math.max(0, steps.indexOf(effort));

  useEffect(() => {
    setModel(settings?.model_name ?? "");
    setEffort(settings?.provider === "custom" ? "" : settings?.reasoning_effort ?? "");
    setError("");
  }, [settings]);
  useEffect(() => {
    setOpen(false); setPickingModel(false); setModels([]); setModelEfforts(null);
  }, [settings?.provider, settings?.base_url, settings?.model_name]);
  useEffect(() => {
    if (!open || !settings || settings.provider === "custom") return;
    let active = true;
    void api.listLLMModels({ provider: settings.provider, base_url: settings.base_url })
      .then((value) => { if (active) { setModels(value.models); setModelEfforts(value.effort_levels ?? null); } })
      .catch(() => { if (active) { setModels([]); setModelEfforts(null); } });
    return () => { active = false; };
  }, [open, settings?.provider, settings?.base_url]);
  useEffect(() => { if (effort && !levels.includes(effort)) setEffort(""); }, [effort, levels]);
  useEffect(() => {
    if (!open) return;
    slider.current?.focus();
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault(); event.stopImmediatePropagation(); setOpen(false); trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside); document.addEventListener("keydown", escape, true);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape, true); };
  }, [open]);

  if (!settings) return null;
  const locked = disabled || saving;
  async function save(nextEffort = effort, close = false) {
    if (!settings || locked) return;
    setSaving(true); setError("");
    try {
      const next = await api.updateLLMSettings({ provider: settings.provider, model_name: model,
        base_url: settings.base_url, temperature: settings.temperature, timeout_seconds: settings.timeout_seconds,
        max_retries: settings.max_retries, reasoning_effort: levels.includes(nextEffort) ? nextEffort : "" });
      onChange(next);
      if (close) { setOpen(false); trigger.current?.focus(); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setSaving(false); }
  }
  const shortModel = (settings?.model_name || "").split("/").pop() || settings?.model_name || (vi ? "Chọn model" : "Select model");
  const activeEffort = label(settings?.provider === "custom" ? "" : settings?.reasoning_effort);

  return <div ref={root} className="relative min-w-0 text-xs" data-composer-model-controls>
    <button ref={trigger} type="button" disabled={locked} aria-expanded={open} aria-haspopup="dialog" aria-controls={dialogId}
      aria-label={`${shortModel} · ${activeEffort || (vi ? "Mặc định" : "Default")}`}
      title={`${settings.model_name}${activeEffort ? ` (${activeEffort})` : ""}`} onClick={() => {
        setModel(settings.model_name); setEffort(settings.provider === "custom" ? "" : settings.reasoning_effort);
        setPickingModel(false); setError(""); setOpen(!open);
      }}
      className="inline-flex h-7 max-w-full items-center gap-1.5 rounded-full border border-border/70 bg-background/80 hover:bg-muted/80 px-2.5 text-xs text-foreground transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50 shadow-xs">
      <Zap size={12} className="shrink-0 text-amber-500 fill-amber-500/20" aria-hidden="true" />
      <span className="truncate max-w-[140px] sm:max-w-[200px] font-medium">{shortModel}</span>
      {activeEffort && (
        <>
          <span className="text-muted-foreground/40 shrink-0">·</span>
          <span className="text-muted-foreground shrink-0 text-[11px]">{activeEffort}</span>
        </>
      )}
      <ChevronDown size={12} className={`shrink-0 text-muted-foreground/70 transition-transform duration-200 ${open ? "rotate-180" : ""}`} aria-hidden="true" />
    </button>
    {open && <section id={dialogId} role="dialog" aria-modal="false" aria-label={vi ? "Model và mức suy nghĩ" : "Model and reasoning"}
      className="absolute bottom-full start-0 z-50 mb-2 max-h-[min(70vh,28rem)] w-72 max-w-[calc(100vw-3rem)] overflow-y-auto rounded-2xl border border-border/70 bg-popover p-3.5 text-popover-foreground shadow-xl animate-in fade-in slide-in-from-bottom-1 duration-150">
      <div className="grid grid-cols-[24px_minmax(0,1fr)_24px] items-start gap-1">
        <Zap size={14} className="mt-0.5 justify-self-start text-muted-foreground/65" aria-hidden="true" />
        <div className="min-w-0 text-center">
          <p aria-live="polite" className="font-medium leading-5 text-[#3155ff] dark:text-[#a4b0ff]">{label(effort)}</p>
          <button type="button" disabled={locked} onClick={() => setPickingModel(!pickingModel)} aria-expanded={pickingModel}
            className="mx-auto flex max-w-full items-center justify-center rounded text-[11px] leading-4 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
            <span className="truncate">{model}</span><ChevronRight size={11} className="shrink-0" aria-hidden="true" />
          </button>
        </div>
        <button type="button" aria-label={vi ? "Đặt lại mức suy nghĩ" : "Reset reasoning effort"} disabled={locked || !levels.length || !effort}
          title={t("settings.providerDefault")} onClick={() => { setEffort(""); void save(""); }}
          className="rounded p-0.5 text-muted-foreground/75 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-35">
          {saving ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
        </button>
      </div>
      <input ref={slider} type="range" min={0} max={Math.max(1, steps.length - 1)} step={1} value={activeLevel}
        disabled={locked || !levels.length} aria-label={vi ? "Mức suy nghĩ" : "Reasoning effort"} aria-valuetext={label(effort)}
        className="composer-reasoning-slider mt-3 block" onChange={(event) => setEffort(steps[Number(event.target.value)] ?? "")}
        onPointerUp={(event) => void save(steps[Number(event.currentTarget.value)] ?? "")}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); event.stopPropagation(); void save(); } }}
        onKeyUp={(event) => { if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"].includes(event.key)) void save(steps[Number(event.currentTarget.value)] ?? ""); }} />
      {!levels.length && <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">{vi ? "Endpoint chưa xác nhận hỗ trợ mức suy nghĩ tùy chọn; dùng mặc định của nhà cung cấp." : "This endpoint has not confirmed effort control; provider defaults apply."}</p>}
      {pickingModel && <div className="mt-3 space-y-2 border-t pt-3">
        <label className="block space-y-1"><span className="text-muted-foreground">Model</span><select aria-label="Model" disabled={settings.provider === "custom" || locked} value={model} onChange={(event) => setModel(event.target.value)} className="w-full rounded-lg border bg-background p-2">
          {[...new Set([settings.model_name, ...models])].map((name) => <option key={name} value={name}>{name}</option>)}
        </select></label>
        {settings.provider === "custom" ? <a href="/settings" className="block text-muted-foreground underline">{vi ? "Đổi model trong cấu hình nhà cung cấp" : "Change model in provider settings"}</a>
          : <button type="button" onClick={() => void save(effort, true)} disabled={locked} className="w-full rounded-lg bg-foreground px-3 py-2 text-background disabled:opacity-50">{vi ? "Áp dụng cho lượt tiếp theo" : "Apply to next turn"}</button>}
      </div>}
      {error && <p role="alert" className="mt-3 text-destructive">{error}</p>}
    </section>}
  </div>;
}
