import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Cpu, Loader2, RotateCcw, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, type LLMSettings } from "@/lib/api";
import { effortLabelKey } from "@/lib/reasoningEffort";
import { cn } from "@/lib/utils";
import "./ComposerModelControls.css";

/**
 * Model + reasoning effort control.
 *
 * Visual model: the trigger is a *quiet* chip (secondary information), the
 * popover is a floating surface on the elevation ladder, and the reasoning
 * effort is expressed through a single heat scale that runs cool → hot.
 */
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

  /* Heat scale: five semantic stops, sampled by the current position. */
  const heatStops = [
    "var(--effort-1)",
    "var(--effort-2)",
    "var(--effort-3)",
    "var(--effort-4)",
    "var(--effort-5)",
  ];
  const heatIndex = Math.min(
    heatStops.length - 1,
    Math.round(effortRatio * (heatStops.length - 1)),
  );
  const effortFill = `hsl(${heatStops[heatIndex]})`;
  const effortGlow = `hsl(${heatStops[heatIndex]} / 0.42)`;
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
        className={cn(
          "vt-focus-visible group inline-flex h-[30px] max-w-full items-center gap-1.5 rounded-full border pl-2.5 pr-2 text-[12.5px] transition-colors duration-fast disabled:opacity-50",
          open
            ? "border-hairline-strong bg-muted text-ink-secondary"
            : "border-hairline bg-surface-panel text-ink-secondary hover:border-hairline-strong hover:bg-muted hover:text-ink",
        )}
      >
        <span
          className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full transition-colors duration-base",
            open ? "bg-accent" : "bg-ink-faint group-hover:bg-accent",
          )}
          aria-hidden="true"
        />
        {open ? (
          <span className="truncate font-medium text-ink-secondary">
            {openEffortPrompt}
          </span>
        ) : (
          <>
            <span className="truncate max-w-[140px] font-semibold text-ink sm:max-w-[200px]">
              {shortModel}
            </span>
            {activeEffort && (
              <span className="hidden shrink-0 font-normal text-ink-faint sm:inline">
                {activeEffort}
              </span>
            )}
          </>
        )}
        <ChevronDown
          size={13}
          className={cn(
            "shrink-0 text-ink-faint transition-transform duration-base",
            open && "rotate-180",
          )}
          aria-hidden="true"
        />
      </button>

      {open && (
        <section
          id={dialogId}
          role="dialog"
          aria-modal="false"
          aria-label={vi ? "Model và mức suy nghĩ" : "Model and reasoning"}
          className="vt-pop-in absolute bottom-full end-0 z-50 mb-2.5 max-h-[70vh] w-[292px] max-w-[calc(100vw-4rem)] overflow-y-auto rounded-xl border border-hairline bg-surface-overlay p-3.5 text-ink shadow-lg sm:end-0"
        >
          {/* Header: effort + model, reset */}
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1 text-center">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-faint">
                {vi ? "Mức suy nghĩ" : "Reasoning"}
              </p>
              <p
                aria-live="polite"
                className="vt-num mt-1 text-[17px] font-semibold leading-6 tracking-tight text-ink"
              >
                {label(effort)}
              </p>
              <button
                type="button"
                disabled={locked}
                onClick={() => setPickingModel(!pickingModel)}
                aria-expanded={pickingModel}
                className="vt-focus-visible mx-auto mt-1.5 flex max-w-full items-center justify-center gap-1 rounded-full bg-muted px-2.5 py-1 text-[11.5px] leading-4 text-ink-secondary transition-colors duration-fast hover:bg-muted/70 hover:text-ink"
              >
                <Cpu size={11} className="shrink-0 text-ink-faint" aria-hidden="true" />
                <span className="max-w-[150px] truncate">
                  {(model || "").split("/").pop() || model}
                </span>
                <ChevronRight
                  size={12}
                  className={cn(
                    "shrink-0 text-ink-faint transition-transform duration-fast",
                    pickingModel && "rotate-90",
                  )}
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
                className="vt-focus-visible rounded-full p-1.5 text-ink-faint transition-colors duration-fast hover:bg-muted hover:text-ink disabled:opacity-35"
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

          {/* Effort selector — semantic heat scale */}
          <div
            className={cn(
              "effort-flow mt-4 rounded-lg border border-hairline-subtle bg-surface-sunken px-3 pb-2.5 pt-3 transition-opacity duration-base",
              (locked || !levels.length) && "opacity-45",
            )}
            style={{
              ["--effort-fill" as string]: effortFill,
              ["--effort-glow" as string]: effortGlow,
            }}
          >
            <div className="relative flex h-[26px] items-center">
              {/* base track */}
              <div className="absolute inset-x-[9px] h-[6px] overflow-hidden rounded-full bg-border">
                <div
                  className="effort-flow-fill h-full rounded-full transition-all duration-slow ease-standard"
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
                    className={cn(
                      "h-[5px] w-[5px] rounded-full transition-all duration-base",
                      idx <= activeLevel ? "bg-ink" : "bg-ink-faint/50",
                    )}
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
                className="pointer-events-none absolute top-1/2 z-10 flex h-[18px] w-[18px] -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-surface-overlay ring-1 ring-hairline-strong transition-all duration-slow ease-standard"
                style={{
                  left:
                    !levels.length || maxStep <= 0
                      ? "9px"
                      : `calc(9px + ${(activeLevel / maxStep)} * (100% - 18px))`,
                  boxShadow: `0 2px 10px ${effortGlow}, 0 0 0 3px ${effortGlow}`,
                }}
              >
                <span
                  className="h-[6px] w-[6px] rounded-full transition-colors duration-slow"
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
                    className="max-w-[64px] truncate text-ink-faint transition-colors duration-slow"
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
            <p className="mt-2.5 text-[11px] leading-relaxed text-ink-muted">
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
                ? "mt-3.5 space-y-2.5 border-t border-hairline-subtle pt-3"
                : "sr-only"
            }
          >
            <label className="block space-y-1">
              <span className="text-[11px] font-medium text-ink-muted">
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
                className="vt-focus-visible w-full rounded-lg border border-hairline bg-surface-panel px-2.5 py-1.5 text-xs text-ink"
              >
                {[...new Set([settings.model_name, ...models])].map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>

            <label className="block space-y-1">
              <span className="text-[11px] font-medium text-ink-muted">
                {vi ? "Mức nỗ lực" : "Reasoning effort"}
              </span>
              <select
                aria-label="Reasoning effort"
                disabled={locked || !levels.length}
                value={levels.includes(effort) ? effort : ""}
                onChange={(event) => setEffort(event.target.value)}
                className="vt-focus-visible w-full rounded-lg border border-hairline bg-surface-panel px-2.5 py-1.5 text-xs text-ink disabled:opacity-50"
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
                className="block text-[11px] text-ink-muted underline transition-colors hover:text-ink"
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
                className="vt-focus-visible w-full rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-accent-foreground transition-colors duration-fast hover:bg-accent-strong disabled:opacity-50"
              >
                {vi ? "Áp dụng cho lượt tiếp theo" : "Apply to next turn"}
              </button>
            )}
          </div>

          {error && (
            <p role="alert" className="mt-2.5 rounded-md bg-destructive/10 px-2 py-1.5 text-[11px] text-destructive">
              {error}
            </p>
          )}
        </section>
      )}
    </div>
  );
}
