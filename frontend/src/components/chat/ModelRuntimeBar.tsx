import { Cpu } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { LLMSettings } from "@/lib/api";
import { effortLabelKey } from "@/lib/reasoningEffort";

interface Props {
  settings: LLMSettings | null;
  runtimeProvider?: string;
  runtimeModel?: string;
  runtimeReasoningEffort?: string;
}

/** Providers often report `vendor/model` while settings store the bare id. */
function comparableModel(value: string | null | undefined): string {
  return (value || "").trim().toLowerCase().split("/").pop() || "";
}

function comparableProvider(value: string | null | undefined): string {
  return (value || "").trim().toLowerCase().replace(/_/g, "-");
}

export function ModelRuntimeBar({
  settings,
  runtimeProvider,
  runtimeModel,
  runtimeReasoningEffort,
}: Props) {
  const { t } = useTranslation();
  if (!settings) return null;

  const providerId = runtimeProvider || settings.provider;
  const provider = settings.providers.find((item) => item.name === providerId);
  const providerLabel = provider?.label || providerId || t("agent.unknownProvider");
  const model = runtimeModel || settings.model_name || t("agent.unknownModel");
  const configuredEffort = settings.reasoning_effort ?? "";
  const reasoningEffort = runtimeReasoningEffort !== undefined
    ? runtimeReasoningEffort
    : configuredEffort;
  const identityMatches = comparableProvider(providerId) === comparableProvider(settings.provider)
    && comparableModel(runtimeModel || settings.model_name) === comparableModel(settings.model_name);
  const effortMatches = reasoningEffort === configuredEffort;
  // The composer already names the model and effort the next turn will use.
  // Keep this bar only for a historical/runtime identity that differs from
  // those settings; repeating an identical identity above the chat is noise.
  if (identityMatches && effortMatches) {
    return null;
  }
  const effortKey = effortLabelKey(reasoningEffort);
  const effortLabel = effortKey ? t(effortKey) : t("settings.providerDefault");

  return (
    <div className="shrink-0 border-b border-hairline-subtle bg-surface-chrome/50 px-6 py-1.5">
      <div className="mx-auto flex max-w-3xl items-center gap-2 overflow-hidden text-[11px]">
        {!identityMatches && <>
          <span className="relative flex h-1.5 w-1.5 shrink-0" aria-hidden="true">
            <span className="absolute inline-flex h-full w-full rounded-full bg-success/30" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-success" />
          </span>
          <span className="shrink-0 font-medium text-ink">{providerLabel}</span>
          <span className="text-ink-faint/60" aria-hidden="true">·</span>
          <span className="truncate font-mono text-[10.5px] text-ink-muted" title={model}>{model}</span>
        </>}
        <a
          href="/settings"
          title={t("settings.reasoningEffortDesc")}
          className="ms-auto hidden shrink-0 items-center gap-1.5 rounded-full border border-hairline bg-surface-sunken/70 px-2.5 py-0.5 text-[10px] text-ink-muted transition-colors hover:bg-muted hover:text-ink cursor-pointer sm:inline-flex"
        >
          <Cpu className="h-3 w-3" aria-hidden="true" />
          <span>{t("agent.reasoningStrength")}: <span className="font-medium text-ink-secondary">{effortLabel}</span></span>
        </a>
      </div>
    </div>
  );
}
