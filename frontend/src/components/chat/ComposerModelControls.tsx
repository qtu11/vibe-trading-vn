import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, RotateCcw, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, type LLMSettings } from "@/lib/api";
import { effortLabelKey } from "@/lib/reasoningEffort";
import "./ComposerModelControls.css";

export function ComposerModelControls({
  settings,
  disabled,
  onChange,
}: {
  settings: LLMSettings | null;
  disabled: boolean;
  onChange: (settings: LLMSettings) => void;
}) {
  const { t, i18n } = useTranslation();
  const vi = i18n.language.startsWith("vi");
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pickingModel, setPickingModel] = useState(false);
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [modelEfforts, setModelEfforts] = useState<Record<string, string[]> | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const slider = useRef<HTMLInputElement>(null);
  const dialogId = useId();

  const provider = settings?.providers.find((p) => p.name === settings.provider);
  const levels = modelEfforts?.[model] ?? provider?.reasoning_efforts ?? [];
  const steps = ["", ...levels];
  const label = (level: string) =>
    effortLabelKey(level)
      ? t(effortLabelKey(level)!)
      : level || t("settings.providerDefault");
  const activeLevel = Math.max(0, steps.indexOf(effort));
  const maxStep = Math.max(1, steps.length - 1);

  useEffect(() => {
    setModel(settings?.model_name ?? "");
    setEffort(settings?.reasoning_effort ?? "");
    setError("");
  }, [settings]);

  useEffect(() => {
    setOpen(false);
    setPickingModel(false);
    setModels([]);
    setModelEfforts(null);
  }, [settings?.provider, settings?.base_url, settings?.model_name]);

  useEffect(() => {
    if (!open || !settings || settings.provider === "custom") return;
    let active = true;
    void api
      .listLLMModels({ provider: settings.provider, base_url: settings.base_url })
      .then((value) => {
        if (active) {
          setModels(value.models);
          setModelEfforts(value.effort_levels ?? null);
        }
      })
      .catch(() => {
        if (active) {
          setModels([]);
          setModelEfforts(null);
        }
      });
    return () => {
      active = false;
    };
  }, [open, settings?.provider, settings?.base_url]);

  useEffect(() => {
    if (effort && !levels.includes(effort)) setEffort("");
  }, [effort, levels]);

  useEffect(() => {
    if (!open) return;
    slider.current?.focus();
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape, true);
    };
  }, [open]);

  if (!settings) return null;
  const locked = disabled || saving;

  async function save(nextEffort = effort, close = false) {
    if (!settings || locked) return;
    const confirmedEffort = levels.includes(nextEffort) ? nextEffort : "";
    if (model === settings.model_name && confirmedEffort === settings.reasoning_effort) {
      if (close) { setOpen(false); trigger.current?.focus(); }
      return;
    }
    setSaving(true);
    setError("");
    try {
      const next = await api.updateLLMSettings({
        provider: settings.provider,
        model_name: model,
        base_url: settings.base_url,
        temperature: settings.temperature,
        timeout_seconds: settings.timeout_seconds,
        max_retries: settings.max_retries,
        reasoning_effort: confirmedEffort,
      });
      onChange(next);
      if (close) {
        setOpen(false);
        trigger.current?.focus();
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  }

  const shortModel =
    (settings.model_name || "").split("/").pop() ||
    settings.model_name ||
    (vi ? "Chọn model" : "Select model");
  const configuredEffort = settings.reasoning_effort;
  const activeEffort = configuredEffort ? label(configuredEffort) : "";
  const openEffortPrompt = vi ? "Chọn mức nỗ lực" : "Select effort";
  const effortRatio = maxStep <= 0 ? 0 : activeLevel / maxStep;
  const effortRamp: Array<[number, number, number]> = [
    [37, 99, 235],
    [59, 130, 246],
    [139, 92, 246],
    [239, 68, 68],
    [153, 27, 27],
  ];
  const effortFill = (() => {
    const clamped = Math.min(1, Math.max(0, effortRatio));
    const scaled = clamped * (effortRamp.length - 1);
    const lo = Math.min(effortRamp.length - 2, Math.floor(scaled));
    const mix = scaled - lo;
    const [r1, g1, b1] = effortRamp[lo];
    const [r2, g2, b2] = effortRamp[lo + 1];
    const r = Math.round(r1 + (r2 - r1) * mix);
    const g = Math.round(g1 + (g2 - g1) * mix);
    const b = Math.round(b1 + (b2 - b1) * mix);
    return `rgb(${r}, ${g}, ${b})`;
  })();
  const effortGlow = effortFill.replace("rgb(", "rgba(").replace(")", ", 0.45)");
  const effortParticles = [
    { left: "6%", delay: "0s", dur: "2.6s", size: 4, top: "30%" },
    { left: "18%", delay: "0.7s", dur: "3.1s", size: 3, top: "62%" },
    { left: "32%", delay: "1.3s", dur: "2.4s", size: 5, top: "44%" },
    { left: "47%", delay: "0.4s", dur: "2.9s", size: 3, top: "28%" },
    { left: "61%", delay: "1.8s", dur: "3.4s", size: 4, top: "58%" },
    { left: "74%", delay: "1.1s", dur: "2.7s", size: 3, top: "38%" },
    { left: "88%", delay: "2s", dur: "3s", size: 4, top: "52%" },
  ];

  return (
    <div ref={root} className="relative min-w-0 text-xs" data-composer-model-controls>
      <button
        ref={trigger}
        type="button"
        disabled={locked}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={dialogId}
        aria-label={activeEffort ? `${shortModel} · ${activeEffort}` : shortModel}
        title={`${settings.model_name}${activeEffort ? ` (${activeEffort})` : ""}`}
        onClick={() => {
          setModel(settings.model_name);
          setEffort(settings.reasoning_effort ?? "");
          setPickingModel(false);
          setError("");
          setOpen(!open);
        }}
        className={`inline-flex h-[30px] max-w-full items-center gap-1.5 rounded-full px-3 text-[12.5px] transition-all focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#3b82f6] disabled:opacity-50 ${
          open
            ? "border border-black/[0.1] dark:border-white/[0.12] bg-black/[0.08] dark:bg-[#27272a] text-muted-foreground shadow-inner"
            : "border border-[#2563eb] dark:border-[#3b82f6] bg-[#2563eb]/10 dark:bg-[#3b82f6]/10 hover:bg-[#2563eb]/20 dark:hover:bg-[#3b82f6]/20 text-foreground shadow-2xs"
        }`}
      >
        {open ? (
          <span className="truncate font-medium text-muted-foreground">
            {openEffortPrompt}
          </span>
        ) : (
          <>
            <span className="truncate max-w-[140px] sm:max-w-[200px] font-semibold text-foreground">
              {shortModel}
            </span>
            {activeEffort && (
              <span className="hidden text-zinc-400 shrink-0 font-normal sm:inline">
                {activeEffort}
              </span>
            )}
          </>
        )}
        <ChevronDown
          size={13}
          className={`shrink-0 text-muted-foreground/80 transition-transform duration-200 ${
            open ? "rotate-180" : ""
          }`}
          aria-hidden="true"
        />
      </button>

      {open && (
        <section
          id={dialogId}
          role="dialog"
          aria-modal="false"
          aria-label={vi ? "Model và mức suy nghĩ" : "Model and reasoning"}
          className="absolute bottom-full -end-10 z-50 mb-3 max-h-[70vh] w-[272px] max-w-[calc(100vw-4rem)] overflow-y-auto rounded-2xl border border-black/[0.1] dark:border-white/[0.12] bg-popover dark:bg-[#1a1b1e] p-3.5 text-popover-foreground shadow-[0_12px_36px_rgba(0,0,0,0.4)] sm:end-0"
        >
          {/* Header: effort + model, reset */}
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1 text-center">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/70">
                {vi ? "Mức suy nghĩ" : "Reasoning"}
              </p>
              <p
                aria-live="polite"
                className="mt-1 text-[17px] font-semibold leading-6 tracking-tight text-foreground"
              >
                {label(effort)}
              </p>
              <button
                type="button"
                disabled={locked}
                onClick={() => setPickingModel(!pickingModel)}
                aria-expanded={pickingModel}
                className="mx-auto mt-1.5 flex max-w-full items-center justify-center gap-1 rounded-full bg-black/[0.04] px-2.5 py-1 text-[11.5px] leading-4 text-muted-foreground transition-colors hover:bg-black/[0.08] hover:text-foreground dark:bg-white/[0.06] dark:hover:bg-white/[0.1] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
              >
                <span className="max-w-[160px] truncate">
                  {(model || "").split("/").pop() || model}
                </span>
                <ChevronRight
                  size={12}
                  className={`shrink-0 transition-transform duration-150 ${
                    pickingModel ? "rotate-90" : ""
                  }`}
                  aria-hidden="true"
                />
              </button>
            </div>
            <div className="flex shrink-0 items-center gap-0.5 pt-0.5">
              <button
                type="button"
                aria-label={vi ? "Đặt lại mức suy nghĩ" : "Reset reasoning effort"}
                disabled={locked || !levels.length || !effort}
                title={t("settings.providerDefault")}
                onClick={() => {
                  setEffort("");
                  void save("");
                }}
                className="rounded-full p-1.5 text-muted-foreground/70 transition-colors hover:bg-black/[0.05] hover:text-foreground dark:hover:bg-white/[0.08] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary disabled:opacity-35"
              >
                {saving ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <RotateCcw size={14} />
                )}
              </button>
              <button
                type="button"
                aria-label={vi ? "Đóng" : "Close"}
                onClick={() => {
                  setOpen(false);
                  trigger.current?.focus();
                }}
                className="sr-only"
              >
                <X size={13} aria-hidden="true" />
              </button>
            </div>
          </div>

          {/* Effort selector — flowing particles, deep red at max */}
          <div
            className={`effort-flow mt-4 rounded-2xl border border-black/[0.06] bg-black/[0.03] px-3 pb-2.5 pt-3 dark:border-white/[0.08] dark:bg-white/[0.04] transition-opacity ${
              locked || !levels.length ? "opacity-45" : ""
            }`}
            style={{ ["--effort-fill" as string]: effortFill, ["--effort-glow" as string]: effortGlow }}
          >
            <div className="relative flex h-[26px] items-center">
              {/* base track */}
              <div className="absolute inset-x-[9px] h-[6px] overflow-hidden rounded-full bg-black/10 dark:bg-white/10">
                <div
                  className="effort-flow-fill h-full rounded-full transition-all duration-500 ease-out"
                  style={{
                    width:
                      !levels.length || maxStep <= 0
                        ? "0%"
                        : `${(activeLevel / maxStep) * 100}%`,
                    background: effortFill,
                    boxShadow: `0 0 12px ${effortGlow}`,
                  }}
                />
                {/* flowing highlight + drifting particles */}
                <div className="effort-flow-sheen" aria-hidden="true" />
                {effortParticles.map((p, i) => (
                  <span
                    key={i}
                    aria-hidden="true"
                    className="effort-flow-particle"
                    style={{
                      left: p.left,
                      top: p.top,
                      width: p.size,
                      height: p.size,
                      animationDelay: p.delay,
                      animationDuration: p.dur,
                    }}
                  />
                ))}
              </div>
              {/* step ticks */}
              <div className="pointer-events-none relative z-10 flex w-full items-center justify-between px-[3px]">
                {steps.map((stepValue, idx) => (
                  <span
                    key={stepValue || `step-${idx}`}
                    className={`h-[5px] w-[5px] rounded-full transition-all duration-300 ${
                      idx <= activeLevel
                        ? "bg-white"
                        : "bg-black/30 dark:bg-white/30"
                    }`}
                    style={
                      idx <= activeLevel
                        ? { boxShadow: `0 0 0 3px ${effortGlow}` }
                        : undefined
                    }
                  />
                ))}
              </div>
              {/* thumb */}
              <div
                className="pointer-events-none absolute top-1/2 z-10 flex h-[18px] w-[18px] -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white ring-1 ring-black/10 transition-all duration-500 ease-out"
                style={{
                  left:
                    !levels.length || maxStep <= 0
                      ? "9px"
                      : `calc(9px + ${(activeLevel / maxStep)} * (100% - 18px))`,
                  boxShadow: `0 2px 10px ${effortGlow}, 0 0 0 3px ${effortGlow}`,
                }}
              >
                <span
                  className="h-[6px] w-[6px] rounded-full transition-colors duration-500"
                  style={{ background: effortFill }}
                />
              </div>
              {/* Interactive Range Input Overlay */}
              <input
                ref={slider}
                type="range"
                min={0}
                max={maxStep}
                step={1}
                value={activeLevel}
                disabled={locked || !levels.length}
                aria-label={vi ? "Mức suy nghĩ" : "Reasoning effort"}
                aria-valuetext={label(effort)}
                className="composer-reasoning-slider absolute inset-0 z-20 m-0 h-full w-full cursor-pointer opacity-0"
                onChange={(event) =>
                  setEffort(steps[Number(event.target.value)] ?? "")
                }
                onPointerUp={(event) =>
                  void save(steps[Number(event.currentTarget.value)] ?? "")
                }
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    event.stopPropagation();
                    void save();
                  }
                }}
                onKeyUp={(event) => {
                  if (
                    [
                      "ArrowLeft",
                      "ArrowRight",
                      "ArrowUp",
                      "ArrowDown",
                      "Home",
                      "End",
                      "PageUp",
                      "PageDown",
                    ].includes(event.key)
                  ) {
                    void save(steps[Number(event.currentTarget.value)] ?? "");
                  }
                }}
              />
            </div>
            {/* level captions */}
            {levels.length > 0 && (
              <div className="mt-1.5 flex items-center justify-between px-[2px] text-[10px] font-medium">
                {steps.map((stepValue, idx) => (
                  <span
                    key={stepValue || `cap-${idx}`}
                    className="max-w-[64px] truncate text-muted-foreground/55 transition-colors duration-500"
                    style={
                      idx === activeLevel
                        ? { color: effortFill }
                        : undefined
                    }
                  >
                    {label(stepValue)}
                  </span>
                ))}
              </div>
            )}
          </div>

          {!levels.length && (
            <p className="mt-2.5 text-[11px] leading-relaxed text-muted-foreground">
              {vi
                ? "Endpoint dùng mức suy nghĩ mặc định của nhà cung cấp."
                : "Provider default reasoning effort applies."}
            </p>
          )}

          {/* Expandable Model & Effort Selectors (always in DOM for a11y & testing) */}
          <div
            hidden={!pickingModel}
            className={
              pickingModel
                ? "mt-3.5 space-y-2.5 border-t border-black/[0.08] dark:border-white/[0.08] pt-3"
                : "sr-only"
            }
          >
            <label className="block space-y-1">
              <span className="text-[11px] font-medium text-muted-foreground">
                Model
              </span>
              <select
                aria-label="Model"
                disabled={settings.provider === "custom" || locked}
                value={model}
                onChange={(event) => {
                  const nextModel = event.target.value;
                  setModel(nextModel);
                  const nextLevels =
                    modelEfforts?.[nextModel] ??
                    provider?.reasoning_efforts ??
                    [];
                  if (effort && !nextLevels.includes(effort)) {
                    setEffort("");
                  }
                }}
                className="w-full rounded-xl border border-black/[0.1] dark:border-white/[0.1] bg-background dark:bg-[#1b1c20] px-2.5 py-1.5 text-xs text-foreground outline-none focus:border-[#3b82f6]"
              >
                {[...new Set([settings.model_name, ...models])].map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>

            <label className="block space-y-1">
              <span className="text-[11px] font-medium text-muted-foreground">
                {vi ? "Mức nỗ lực" : "Reasoning effort"}
              </span>
              <select
                aria-label="Reasoning effort"
                disabled={locked || !levels.length}
                value={levels.includes(effort) ? effort : ""}
                onChange={(event) => setEffort(event.target.value)}
                className="w-full rounded-xl border border-black/[0.1] dark:border-white/[0.1] bg-background dark:bg-[#1b1c20] px-2.5 py-1.5 text-xs text-foreground outline-none focus:border-[#3b82f6] disabled:opacity-50"
              >
                <option value="">{t("settings.providerDefault")}</option>
                {levels.map((lvl) => (
                  <option key={lvl} value={lvl}>
                    {label(lvl)}
                  </option>
                ))}
              </select>
            </label>

            {settings.provider === "custom" ? (
              <a
                href="/settings"
                className="block text-[11px] text-muted-foreground underline hover:text-foreground"
              >
                {vi
                  ? "Đổi model trong cấu hình nhà cung cấp"
                  : "Change model in provider settings"}
              </a>
            ) : (
              <button
                type="button"
                onClick={() => void save(effort, true)}
                disabled={locked}
                className="w-full rounded-xl bg-[#2b7fff] hover:bg-[#3b8aff] px-3 py-2 text-xs font-medium text-white transition-colors disabled:opacity-50"
              >
                {vi ? "Áp dụng cho lượt tiếp theo" : "Apply to next turn"}
              </button>
            )}
          </div>

          {error && (
            <p role="alert" className="mt-2.5 text-[11px] text-destructive">
              {error}
            </p>
          )}
        </section>
      )}
    </div>
  );
}
