import type { ToolCallEntry } from "@/types/agent";

/**
 * The execution model behind the AI Execution Intelligence Panel.
 *
 * A run is not a flat list of tool calls: it is a sequence of research
 * phases. Flattening them into one wall of rows is what made the old log
 * unreadable, so the panel groups calls into the phases below and shows
 * progress at the phase level first.
 *
 * The classifier is intentionally conservative: a call whose tool matches no
 * rule lands in "analysis", which is the phase the user is already reading.
 */
export type ExecutionPhaseId =
  | "planning"
  | "collection"
  | "modeling"
  | "verification"
  | "reporting";

export interface ExecutionPhaseDefinition {
  id: ExecutionPhaseId;
  labelKey: string;
  /** Lucide icon name is resolved by the caller to keep this module data-only. */
  descriptionKey: string;
}

export const EXECUTION_PHASES: ExecutionPhaseDefinition[] = [
  { id: "planning", labelKey: "execution.phases.planning", descriptionKey: "execution.phases.planningHint" },
  { id: "collection", labelKey: "execution.phases.collection", descriptionKey: "execution.phases.collectionHint" },
  { id: "modeling", labelKey: "execution.phases.modeling", descriptionKey: "execution.phases.modelingHint" },
  { id: "verification", labelKey: "execution.phases.verification", descriptionKey: "execution.phases.verificationHint" },
  { id: "reporting", labelKey: "execution.phases.reporting", descriptionKey: "execution.phases.reportingHint" },
];

const PHASE_RULES: Array<{ id: ExecutionPhaseId; pattern: RegExp }> = [
  {
    id: "planning",
    pattern: /(load_skill|spawn_subagent|create_task|update_task|compact|run_swarm|plan|memory)/,
  },
  {
    id: "collection",
    pattern: /(market_data|read_url|read_document|read_file|web_search|parallel_web_search|concurrent_scraper|screen_market|ticker|quote|candle|orderbook|funding|open_interest|filing|news|profile|screener|fred|iwencai|fund_flow|dragon|northbound|margin|block_trade|shareholder|lockup|sector|options_chain|financial|fundamentals|trading_|get_forex|fetch|search|bash)/,
  },
  {
    id: "modeling",
    pattern: /(write_file|edit_file|patch|backtest|strategy|signal|scaffold|generate|code|simulate|optimi[sz]e|factor|options_payoff|portfolio)/,
  },
  {
    id: "verification",
    pattern: /(validate|validation|rigor|monte_carlo|bootstrap|walk_forward|stress_test|sanity_check|verify|cross_check|audit)/,
  },
  {
    id: "reporting",
    pattern: /(render_shadow_report|report|artifact|document|export|summary|write_report)/,
  },
];

export function classifyToolPhase(tool: string): ExecutionPhaseId {
  const normalized = (tool || "").toLowerCase();
  for (const rule of PHASE_RULES) {
    if (rule.pattern.test(normalized)) return rule.id;
  }
  return "modeling";
}

export type PhaseStatus = "pending" | "running" | "done" | "error";

export interface ExecutionPhaseGroup {
  id: ExecutionPhaseId;
  /** Tool calls belonging to this phase, in chronological order. */
  steps: ToolCallEntry[];
  status: PhaseStatus;
  /** Wall-clock milliseconds spent in this phase. */
  elapsedMs: number;
  /** Number of failed calls in this phase. */
  errors: number;
}

/** Merge a phase's calls into a single status. */
function phaseStatus(steps: ToolCallEntry[]): PhaseStatus {
  if (steps.some((step) => step.status === "running")) return "running";
  if (steps.some((step) => step.status === "error")) return "error";
  if (steps.length > 0) return "done";
  return "pending";
}

function stepElapsedMs(step: ToolCallEntry): number {
  if (typeof step.elapsed_ms === "number") return step.elapsed_ms;
  if (typeof step.elapsed_s === "number") return step.elapsed_s * 1000;
  return 0;
}

/**
 * Group tool calls into execution phases.
 *
 * Phases are returned in the canonical research order rather than the order
 * they first appeared, so the panel always reads top-to-bottom as a plan.
 * A phase with no calls is omitted entirely.
 */
export function groupStepsIntoPhases(steps: ToolCallEntry[]): ExecutionPhaseGroup[] {
  const buckets = new Map<ExecutionPhaseId, ToolCallEntry[]>();
  for (const step of steps) {
    const phase = classifyToolPhase(step.tool);
    const bucket = buckets.get(phase);
    if (bucket) bucket.push(step);
    else buckets.set(phase, [step]);
  }

  const groups: ExecutionPhaseGroup[] = [];
  for (const phase of EXECUTION_PHASES) {
    const phaseSteps = buckets.get(phase.id);
    if (!phaseSteps || phaseSteps.length === 0) continue;
    groups.push({
      id: phase.id,
      steps: phaseSteps,
      status: phaseStatus(phaseSteps),
      elapsedMs: phaseSteps.reduce((sum, step) => sum + stepElapsedMs(step), 0),
      errors: phaseSteps.filter((step) => step.status === "error").length,
    });
  }
  return groups;
}

/** The phase that is currently making progress, if any. */
export function activePhaseId(groups: ExecutionPhaseGroup[]): ExecutionPhaseId | null {
  const running = groups.find((group) => group.status === "running");
  return running ? running.id : null;
}
