import {
  memo,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type JSX,
} from "react";
import { useTranslation } from "react-i18next";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Loader2,
  Octagon,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { localizeToolName } from "@/lib/tools";
import { ExecutionPanel } from "@/components/chat/ExecutionPanel";
import type { AgentActivity } from "@/stores/agent";

interface ActivityLineProps {
  activity: AgentActivity;
  /** Live rolling reasoning excerpt — only supplied for the in-flight attempt. */
  reasoningTail?: string;
  onContinue?: () => void;
  onReattach?: () => void;
}

const ACTIVE_STATES = new Set<AgentActivity["state"]>([
  "thinking",
  "working",
  "responding",
]);

export function formatActivityElapsed(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  return `${Math.floor(totalSeconds / 60)}m ${totalSeconds % 60}s`;
}

function StateIcon({ state }: { state: AgentActivity["state"] }): JSX.Element {
  if (ACTIVE_STATES.has(state)) {
    return <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" aria-hidden="true" />;
  }
  if (state === "done") {
    return <CheckCircle2 className="h-3.5 w-3.5 text-success" aria-hidden="true" />;
  }
  if (state === "stopped") {
    return <Octagon className="h-3.5 w-3.5 text-ink-faint" aria-hidden="true" />;
  }
  if (state === "timeout") {
    return <Clock3 className="h-3.5 w-3.5 text-warning" aria-hidden="true" />;
  }
  return <XCircle className="h-3.5 w-3.5 text-danger" aria-hidden="true" />;
}

/** The single live and historical status surface for one agent attempt. */
export const ActivityLine = memo(function ActivityLine({
  activity,
  reasoningTail,
  onContinue,
  onReattach,
}: ActivityLineProps): JSX.Element {
  const { t } = useTranslation();
  const detailsId = useId();
  const isActive = ACTIVE_STATES.has(activity.state);
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const [autoOpen, setAutoOpen] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const intervalRef = useRef(0);
  const expanded = userOpen ?? autoOpen;

  useEffect(() => {
    if (isActive) {
      setAutoOpen(true);
      return;
    }
    const timer = window.setTimeout(() => setAutoOpen(false), 900);
    return () => window.clearTimeout(timer);
  }, [isActive]);

  useEffect(() => {
    const stopTimer = () => {
      window.clearInterval(intervalRef.current);
      intervalRef.current = 0;
    };
    if (!isActive) {
      stopTimer();
      setNow(activity.endedAt ?? Date.now());
      return stopTimer;
    }

    const syncTimer = () => {
      stopTimer();
      if (document.hidden) return;
      setNow(Date.now());
      intervalRef.current = window.setInterval(() => setNow(Date.now()), 1000);
    };
    syncTimer();
    document.addEventListener("visibilitychange", syncTimer);
    return () => {
      document.removeEventListener("visibilitychange", syncTimer);
      stopTimer();
    };
  }, [activity.endedAt, isActive]);

  const elapsed = formatActivityElapsed(
    Math.max(0, (activity.endedAt ?? now) - activity.startedAt),
  );
  const stepCount = activity.steps.length;
  const stepsLabel = t("agent.activity.steps" as never, { count: stepCount });
  const verb = t(`agent.activity.verbs.${activity.verb}` as never);
  const newestStep = activity.steps[activity.steps.length - 1];

  const summary = useMemo(() => {
    if (activity.state === "stopped") {
      return `${t("agent.activity.stopped" as never)} · ${stepsLabel} · ${elapsed}`;
    }
    if (activity.state === "timeout") {
      return `${t("agent.activity.timeout" as never, { elapsed })} · ${stepsLabel}`;
    }
    if (activity.state === "failed") {
      return `${t("agent.activity.failed" as never)} · ${stepsLabel} · ${elapsed}`;
    }
    if (activity.state === "done") {
      return `${t("agent.activity.done" as never)} · ${stepsLabel} · ${elapsed}`;
    }
    const latest = newestStep ? localizeToolName(newestStep.tool) : "";
    return [verb, latest, elapsed, stepsLabel].filter(Boolean).join(" · ");
  }, [activity.state, elapsed, newestStep, stepsLabel, t, verb]);

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="false"
      className="relative"
    >
      <div
        className={cn(
          "relative overflow-hidden rounded-xl border shadow-panel transition-colors duration-[--dur-fast]",
          isActive
            ? "border-accent/25 bg-accent/[0.035]"
            : activity.state === "failed"
              ? "border-danger/25 bg-danger/[0.04]"
              : "border-hairline-subtle bg-surface-panel/70",
        )}
      >
      {/* Status edge: a thin accent rail that encodes the attempt's state
          without adding another icon to the summary row. */}
      <span
        aria-hidden="true"
        className={cn(
          "absolute inset-y-0 start-0 w-[2px]",
          isActive
            ? "bg-accent"
            : activity.state === "done"
              ? "bg-success"
              : activity.state === "failed"
                ? "bg-danger"
                : activity.state === "timeout"
                  ? "bg-warning"
                  : "bg-ink-faint/50",
        )}
      />
      <button
        type="button"
        aria-controls={detailsId}
        aria-expanded={expanded}
        onClick={() => setUserOpen(!expanded)}
        className={cn(
          "vt-focus-visible flex min-h-9 w-full min-w-0 items-center gap-2 px-3 py-2 text-[13px]",
          "transition-colors duration-[--dur-fast] hover:bg-muted/60",
        )}
      >
        <span className="flex h-4 w-4 shrink-0 items-center justify-center">
          <StateIcon state={activity.state} />
        </span>
        <span className="min-w-0 flex-1 truncate text-start text-ink-secondary">
          {summary}
        </span>
        {expanded
          ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-ink-faint" aria-hidden="true" />
          : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ink-faint" aria-hidden="true" />}
      </button>

      <div id={detailsId} hidden={!expanded}>
        {/* Live reasoning whisper — a sub-trace of the current thought; it
            disappears once the attempt leaves its active states. */}
        {isActive && reasoningTail && (
          <div className="border-t border-hairline-subtle px-3 py-2.5" aria-hidden="true">
            <p className="line-clamp-3 border-s-2 border-accent/30 ps-2.5 font-serif text-xs italic leading-relaxed text-ink-muted">
              {reasoningTail}
            </p>
          </div>
        )}
        {activity.steps.length > 0 && (
          <div className="border-t border-hairline-subtle px-3 py-2.5">
            <ExecutionPanel toolCalls={activity.steps} />
          </div>
        )}
        {(activity.state === "stopped" && onContinue) && (
          <div className="flex justify-end border-t border-hairline-subtle px-3 py-2">
            <button
              type="button"
              onClick={onContinue}
              className="vt-focus-visible rounded-md border border-hairline px-3 py-1 text-xs font-medium text-ink transition-colors hover:bg-muted"
            >
              {t("agent.activity.continue" as never)}
            </button>
          </div>
        )}
        {(activity.state === "timeout" && onReattach) && (
          <div className="flex justify-end border-t border-hairline-subtle px-3 py-2">
            <button
              type="button"
              onClick={onReattach}
              className="vt-focus-visible rounded-md border border-hairline px-3 py-1 text-xs font-medium text-ink transition-colors hover:bg-muted"
            >
              {t("agent.activity.reattach" as never)}
            </button>
          </div>
        )}
      </div>
      </div>
    </div>
  );
});
