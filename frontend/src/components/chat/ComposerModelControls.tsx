import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, RotateCcw, X, Zap } from "lucide-react";
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
  const levels =
    settings?.provider === "custom"
      ? []
      : modelEfforts?.[model] ?? provider?.reasoning_efforts ?? [];
  const steps = ["", ...levels];
  const label = (level: string) =>
    effortLabelKey(level)
      ? t(effortLabelKey(level)!)
      : level || t("settings.providerDefault");
  const activeLevel = Math.max(0, steps.indexOf(effort));
  const maxStep = Math.max(1, steps.length - 1);
  const progressPercent = steps.length > 1 ? (activeLevel / maxStep) * 100 : 100;

  useEffect(() => {
    setModel(settings?.model_name ?? "");
    setEffort(settings?.provider === "custom" ? "" : settings?.reasoning_effort ?? "");
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
        reasoning_effort: levels.includes(nextEffort) ? nextEffort : "",
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
  const activeEffort = label(
    settings.provider === "custom" ? "" : settings.reasoning_effort,
  );
  const openEffortPrompt = vi ? "Chọn mức nỗ lực" : "Select effort";

  return (
    <div ref={root} className="relative min-w-0 text-xs" data-composer-model-controls>
      <button
        ref={trigger}
        type="button"
        disabled={locked}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={dialogId}
        aria-label={`${shortModel} · ${activeEffort || (vi ? "Mặc định" : "Default")}`}
        title={`${settings.model_name}${activeEffort ? ` (${activeEffort})` : ""}`}
        onClick={() => {
          setModel(settings.model_name);
          setEffort(settings.provider === "custom" ? "" : settings.reasoning_effort);
          setPickingModel(false);
          setError("");
          setOpen(!open);
        }}
        className={`inline-flex h-7 max-w-full items-center gap-1.5 rounded-full px-3 text-[12.5px] transition-all focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#3b82f6] disabled:opacity-50 ${
          open
            ? "border border-black/[0.1] dark:border-white/[0.1] bg-black/[0.08] dark:bg-white/[0.09] text-muted-foreground"
            : "border border-black/[0.1] dark:border-white/[0.12] bg-black/[0.03] dark:bg-white/[0.04] hover:bg-black/[0.07] dark:hover:bg-white/[0.08] hover:border-[#3b82f6]/60 text-foreground"
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
              <span className="text-muted-foreground shrink-0 font-normal">
                {activeEffort}
              </span>
            )}
          </>
        )}
        <ChevronDown
          size={13}
          className={`shrink-0 text-muted-foreground/75 transition-transform duration-200 ${
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
          className="absolute bottom-full end-0 z-50 mb-2.5 max-h-[min(75vh,30rem)] w-72 max-w-[calc(100vw-2rem)] overflow-y-auto rounded-[20px] border border-black/[0.1] dark:border-white/[0.1] bg-popover dark:bg-[#25262a] p-4 text-popover-foreground shadow-[0_16px_40px_rgba(0,0,0,0.48)] animate-in fade-in slide-in-from-bottom-1 duration-150"
        >
          {/* Header: Zap icon | Effort + Model | Reset & Close */}
          <div className="grid grid-cols-[24px_minmax(0,1fr)_auto] items-start gap-1">
            <Zap
              size={15}
              className="mt-0.5 justify-self-start text-muted-foreground/75"
              aria-hidden="true"
            />
            <div className="min-w-0 text-center">
              <p
                aria-live="polite"
                className="text-[13.5px] font-semibold leading-5 text-[#2b7fff] dark:text-[#4d9eff]"
              >
                {label(effort)}
              </p>
              <button
                type="button"
                disabled={locked}
                onClick={() => setPickingModel(!pickingModel)}
                aria-expanded={pickingModel}
                className="mx-auto mt-0.5 flex max-w-full items-center justify-center gap-0.5 rounded px-1.5 py-0.5 text-[12px] leading-4 text-muted-foreground hover:text-foreground hover:bg-black/[0.05] dark:hover:bg-white/[0.06] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
              >
                <span className="truncate">
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
            <div className="flex items-center gap-0.5">
              <button
                type="button"
                aria-label={vi ? "Đặt lại mức suy nghĩ" : "Reset reasoning effort"}
                disabled={locked || !levels.length || !effort}
                title={t("settings.providerDefault")}
                onClick={() => {
                  setEffort("");
                  void save("");
                }}
                className="rounded-md p-1 text-muted-foreground/75 hover:text-foreground hover:bg-black/[0.05] dark:hover:bg-white/[0.06] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary disabled:opacity-35"
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

          {/* Codex Segmented Blue Pill Slider */}
          <div
            className={`relative mt-3.5 flex h-7 items-center rounded-full bg-zinc-200 dark:bg-[#383a40] px-1 ${
              locked || !levels.length ? "opacity-45" : ""
            }`}
          >
            {/* Active Blue Fill Bar */}
            <div
              className="pointer-events-none absolute inset-y-0 left-0 rounded-full bg-[#2b7fff] transition-all duration-150"
              style={{
                width:
                  steps.length > 1
                    ? `calc(${progressPercent}% + ${
                        ((50 - progressPercent) / 50) * 12
                      }px)`
                    : "100%",
              }}
            />
            {/* Discrete Step Dots */}
            <div className="pointer-events-none relative z-10 flex w-full items-center justify-between px-2.5">
              {steps.map((stepValue, idx) => (
                <span
                  key={stepValue || `step-${idx}`}
                  className={`h-1 w-1 rounded-full transition-colors ${
                    idx <= activeLevel
                      ? "bg-white/70"
                      : "bg-black/30 dark:bg-white/30"
                  }`}
                />
              ))}
            </div>
            {/* Crisp White Thumb */}
            <div
              className="pointer-events-none absolute top-1/2 z-10 h-5 w-5 -translate-y-1/2 rounded-full bg-white shadow-[0_2px_6px_rgba(0,0,0,0.4)] transition-all duration-150"
              style={{
                left: `calc(${progressPercent}% - ${(progressPercent / 100) * 20}px + ${
                  (1 - progressPercent / 100) * 4 - (progressPercent / 100) * 4
                }px)`,
              }}
            />
            {/* Interactive Range Input */}
            <input
              ref={slider}
              type="range"
              min={0}
              max={maxStep}
              step={1}
              value={activeLevel}
              disabled={locked || !levels.length}
              aria-label={vi ? "Thanh trượt mức suy nghĩ" : "Reasoning effort slider"}
              aria-valuetext={label(effort)}
              className="composer-reasoning-slider absolute inset-0 z-20 m-0 h-full w-full opacity-0"
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

          {!levels.length && (
            <p className="mt-2.5 text-[11px] leading-relaxed text-muted-foreground">
              {vi
                ? "Endpoint dùng mức suy nghĩ mặc định của nhà cung cấp."
                : "Provider default reasoning effort applies."}
            </p>
          )}

          {/* Expandable Model & Effort Selectors (always in DOM for a11y & testing) */}
          <div
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
                    settings.provider === "custom"
                      ? []
                      : modelEfforts?.[nextModel] ??
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
