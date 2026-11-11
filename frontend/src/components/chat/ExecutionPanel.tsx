import { memo, useMemo, useState, type JSX } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  Check,
  ClipboardList,
  Database,
  FileOutput,
  Loader2,
  Search,
  ShieldCheck,
  Terminal,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ToolProgressIndicator } from "@/components/chat/ToolProgressIndicator";
import {
  EXECUTION_PHASES,
  groupStepsIntoPhases,
  type ExecutionPhaseGroup,
  type ExecutionPhaseId,
} from "@/components/chat/executionPhases";
import type { ToolCallEntry } from "@/types/agent";

const PHASE_ICON: Record<ExecutionPhaseId, typeof Search> = {
  planning: ClipboardList,
  collection: Database,
  modeling: Search,
  verification: ShieldCheck,
  reporting: FileOutput,
};

/**
 * The AI Execution Intelligence Panel.
 *
 * The previous agent log was a flat list of tool rows: every call carried
 * the same visual weight, so a 200-step run was unreadable. This panel
 * inverts the priority — the phase rail states what the agent is doing at a
 * glance, and the individual calls stay one disclosure away.
 *
 * The phase sections use native <details> so they work with the keyboard and
 * screen readers without adding a second button to an already busy surface.
 */
export const ExecutionPanel = memo(function ExecutionPanel({
  toolCalls,
  collapsible = true,
}: {
  toolCalls: ToolCallEntry[];
  collapsible?: boolean;
}): JSX.Element | null {
  const { t } = useTranslation();
  const groups = useMemo(() => groupStepsIntoPhases(toolCalls), [toolCalls]);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return groups;
    return groups
      .map((group) => ({
        ...group,
        steps: group.steps.filter((step) =>
          step.tool.toLowerCase().includes(needle)
          || Object.values(step.arguments ?? {}).some((value) =>
            typeof value === "string" && value.toLowerCase().includes(needle),
          ),
        ),
      }))
      .filter((group) => group.steps.length > 0);
  }, [groups, query]);

  if (groups.length === 0) return null;

  const shown = filtered;
  const totalSteps = groups.reduce((sum, group) => sum + group.steps.length, 0);
  const totalElapsed = groups.reduce((sum, group) => sum + group.elapsedMs, 0);
  const failedCalls = groups.reduce((sum, group) => sum + group.errors, 0);

  return (
    <div className="min-w-0 overflow-hidden rounded-xl border border-hairline-subtle bg-surface-panel/70 shadow-panel" data-execution-panel>
      {/* Header — the run's identity and health at a glance. */}
      <div className="flex flex-wrap items-center gap-2 border-b border-hairline-subtle bg-surface-sunken/50 px-3 py-2">
        <span className="flex h-5 w-5 items-center justify-center rounded-md bg-accent/12 text-accent-ink">
          <Terminal aria-hidden="true" className="h-3 w-3" />
        </span>
        <span className="text-[11.5px] font-semibold uppercase tracking-[0.1em] text-ink-secondary">
          {t("execution.phaseRail" as never)}
        </span>
        <span className="ms-auto flex items-center gap-2 text-[10.5px] text-ink-faint">
          <span className="vt-tabular">
            {totalSteps} {t("execution.toolCount" as never)}
          </span>
          {totalElapsed > 0 && (
            <span className="vt-tabular">{formatPhaseElapsed(totalElapsed)}</span>
          )}
          {failedCalls > 0 && (
            <span className="inline-flex items-center gap-1 font-medium text-danger">
              <AlertTriangle aria-hidden="true" className="h-3 w-3" />
              {failedCalls} {t("execution.failedPhases" as never)}
            </span>
          )}
        </span>
      </div>

      {/* Phase rail — the at-a-glance layer. */}
      <ol
        className="flex min-w-0 flex-wrap items-center gap-1 px-3 pt-2.5"
        aria-label={t("execution.phaseRail" as never)}
      >
        {groups.map((group, index) => (
          <PhaseChip key={group.id} group={group} index={index} total={groups.length} />
        ))}
      </ol>

      {/* Log filter — only worth the space once the run is long enough. */}
      {totalSteps >= 8 && (
        <div className="px-3 pt-2.5">
          <label className="relative flex items-center">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute start-2 h-3.5 w-3.5 text-ink-faint"
            />
            <span className="sr-only">{t("execution.filterLogs" as never)}</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("execution.filterLogs" as never)}
              className={cn(
                "vt-focus-visible h-7 w-full rounded-md border border-hairline bg-surface-sunken/60 ps-7 pe-2",
                "text-[11.5px] text-ink placeholder:text-ink-faint",
                "transition-colors duration-fast focus:bg-surface-panel",
              )}
            />
          </label>
        </div>
      )}

      {/* Detail layer — one disclosure per phase. */}
      <div className="space-y-1.5 p-3">
        {shown.map((group) => {
          const definition = EXECUTION_PHASES.find((phase) => phase.id === group.id);
          const Icon = PHASE_ICON[group.id];
          const header = (
            <>
              <Icon
                aria-hidden="true"
                className={cn(
                  "h-3.5 w-3.5 shrink-0",
                  group.status === "running"
                    ? "text-accent"
                    : group.status === "error"
                      ? "text-danger"
                      : "text-ink-faint",
                )}
              />
              <span className="min-w-0 truncate text-[12px] font-medium text-ink-secondary">
                {definition ? t(definition.labelKey as never) : group.id}
              </span>
              <span className="vt-tabular shrink-0 text-[10px] text-ink-faint">
                {group.steps.length} {t("execution.toolCount" as never)}
              </span>
              {group.errors > 0 && (
                <span className="inline-flex items-center gap-1 text-[10px] font-medium text-danger">
                  <AlertTriangle aria-hidden="true" className="h-3 w-3" />
                  {group.errors}
                </span>
              )}
              <span className="ms-auto flex shrink-0 items-center gap-2">
                {group.elapsedMs > 0 && (
                  <span className="vt-tabular text-[10px] text-ink-faint">
                    {formatPhaseElapsed(group.elapsedMs)}
                  </span>
                )}
                <PhaseStatusIcon status={group.status} />
              </span>
            </>
          );
          const body = (
            <div className="border-t border-hairline-subtle px-2.5 py-2">
              {definition && (
                <p className="mb-1.5 text-[11px] leading-relaxed text-ink-faint">
                  {t(definition.descriptionKey as never)}
                </p>
              )}
              <ToolProgressIndicator toolCalls={group.steps} />
            </div>
          );
          const shell = cn(
            "group/phase overflow-hidden rounded-lg border transition-colors duration-fast",
            group.status === "running"
              ? "border-accent/25 bg-accent/[0.04]"
              : group.status === "error"
                ? "border-danger/25 bg-danger/[0.04]"
                : "border-hairline-subtle bg-surface-panel/60",
          );
          // `collapsible={false}` renders the phases flat: every call is
          // visible without a disclosure step. Used where the panel is the
          // only content of its surface and depth would only add clicks.
          if (!collapsible) {
            return (
              <section key={group.id} className={shell}>
                <div className="flex min-w-0 items-center gap-2 px-2.5 py-1.5">{header}</div>
                {body}
              </section>
            );
          }
          return (
            <details key={group.id} open className={shell}>
              <summary
                className={cn(
                  "flex cursor-pointer list-none min-w-0 items-center gap-2 px-2.5 py-1.5 text-start",
                  "transition-colors duration-fast hover:bg-muted/50",
                  "[&::-webkit-details-marker]:hidden",
                )}
              >
                {header}
              </summary>
              {body}
            </details>
          );
        })}
        {shown.length === 0 && (
          <p className="px-1 py-2 text-[11px] text-ink-faint">
            {t("execution.noMatchingTools" as never)}
          </p>
        )}
      </div>
    </div>
  );
});

function PhaseStatusIcon({ status }: { status: ExecutionPhaseGroup["status"] }) {
  if (status === "running") {
    return <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin text-accent" />;
  }
  if (status === "error") {
    return <AlertTriangle aria-hidden="true" className="h-3.5 w-3.5 text-danger" />;
  }
  if (status === "done") {
    return <Check aria-hidden="true" className="h-3.5 w-3.5 text-success" />;
  }
  return <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-ink-faint" />;
}

function PhaseChip({
  group,
  index,
  total,
}: {
  group: ExecutionPhaseGroup;
  index: number;
  total: number;
}) {
  const { t } = useTranslation();
  const definition = EXECUTION_PHASES.find((phase) => phase.id === group.id);
  const label = definition ? t(definition.labelKey as never) : group.id;
  return (
    <li className="flex min-w-0 items-center gap-1">
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10.5px] font-medium transition-colors",
          group.status === "running"
            ? "border-accent/30 bg-accent/10 text-accent-ink shadow-[0_0_0_3px_hsl(var(--accent)/0.07)]"
            : group.status === "error"
              ? "border-danger/30 bg-danger/10 text-danger"
              : "border-hairline bg-muted/50 text-ink-secondary",
        )}
      >
        <PhaseStatusIcon status={group.status} />
        <span className="truncate">{label}</span>
      </span>
      {index < total - 1 && (
        <span aria-hidden="true" className="h-px w-3 shrink-0 bg-hairline" />
      )}
    </li>
  );
}

function formatPhaseElapsed(milliseconds: number): string {
  const seconds = Math.round(milliseconds / 100) / 10;
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}
