import type { ForexResearchEvidence } from "./forexApi";

/** Versioned research metadata from the first-party Forex tool. Never parse prose. */
export type ForexSide = "buy" | "sell";
export interface ForexScenario {
  side: ForexSide;
  order_type: "market" | "limit";
  entry: string;
  stop_loss: string;
  take_profit: string;
  reward_risk: string;
  basis: "atr_structure_v1";
}
export interface ForexCouncilReport {
  role: "technical" | "macro" | "bull" | "bear" | "risk" | "manager";
  stance: ForexSide | "wait";
  entry_mode: "market" | "limit";
  summary: string;
  counterargument: string;
  evidence_refs: string[];
  veto: boolean;
  provider: string;
  model: string;
  elapsed_ms: number;
  forecast?: { direction: "up" | "down" | "range" | "uncertain"; timeframe: "5m" | "1h" | "4h" | "1d"; horizon_bars: 6; rationale: string; invalidation: string } | null;
}
export interface ForexTradePlan {
  version: 1;
  plan_id: string;
  symbol: string;
  connection_id?: string | null;
  currency: string;
  source: "mt5";
  environment: "demo" | "live";
  broker_server: string;
  binding_hash: string;
  evidence_hash: string;
  created_at: string;
  expires_at: string;
  quote_at: string;
  bid: string;
  ask: string;
  price_step: string | null;
  minimum_stop_distance: string | null;
  status: "ready" | "wait" | "blocked";
  recommendation: ForexSide | "wait";
  reasons: string[];
  scenarios: ForexScenario[];
  reports: ForexCouncilReport[];
  unique_models: number;
  evidence?: ForexResearchEvidence | null;
  failures?: Array<{ role: ForexCouncilReport["role"]; code: string }>;
  llm_usage?: ForexCouncilUsage | null;
  workflow: "bounded_research_council_v1";
  trading_performed: false;
}

export interface ForexCouncilUsage {
  scope: "forex_council"; reported_calls: number; attempted_calls: number; missing_calls: number;
  totals: Record<string, number> | null;
  per_role: Array<{ role: ForexCouncilReport["role"]; usage: Record<string, number> | null }>;
}

const decimal = (v: unknown): v is string => typeof v === "string"
  && /^\d+(?:\.\d+)?$/.test(v) && Number.isFinite(Number(v)) && Number(v) > 0;
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object";
const iso = (v: unknown): v is string => typeof v === "string" && /(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));

export function parseForexTradePlan(value: unknown): ForexTradePlan | undefined {
  if (!record(value) || value.version !== 1 || value.source !== "mt5"
    || value.workflow !== "bounded_research_council_v1" || value.trading_performed !== false
    || typeof value.symbol !== "string" || typeof value.currency !== "string"
    || typeof value.broker_server !== "string" || typeof value.evidence_hash !== "string"
    || !["demo", "live"].includes(String(value.environment))
    || !["ready", "wait", "blocked"].includes(String(value.status))
    || !["buy", "sell", "wait"].includes(String(value.recommendation))
    || !iso(value.quote_at) || !iso(value.created_at) || !iso(value.expires_at)
    || Date.parse(value.expires_at) <= Date.parse(value.created_at)
    || Date.parse(value.expires_at) - Date.parse(value.created_at) > 65000
    || !decimal(value.bid) || !decimal(value.ask) || Number(value.ask) < Number(value.bid)
    || !Array.isArray(value.scenarios) || value.scenarios.length > 2
    || !Array.isArray(value.reports) || value.reports.length > 6
    || !Array.isArray(value.reasons) || !value.reasons.every(v => typeof v === "string")
    || !Number.isInteger(value.unique_models)) return undefined;
  const sides = new Set<string>();
  if (value.llm_usage != null) {
    const u = value.llm_usage;
    if (!record(u) || u.scope !== "forex_council" || ![u.reported_calls, u.attempted_calls, u.missing_calls].every(n => typeof n === "number" && Number.isInteger(n) && n >= 0 && n <= 6)
      || Number(u.reported_calls) + Number(u.missing_calls) !== u.attempted_calls || !Array.isArray(u.per_role) || u.per_role.length !== u.attempted_calls
      || (u.totals != null && (!record(u.totals) || !Object.values(u.totals).every(n => typeof n === "number" && Number.isFinite(n) && n >= 0)))
      || !u.per_role.every(r => record(r) && typeof r.role === "string" && (r.usage == null || (record(r.usage) && Object.values(r.usage).every(n => typeof n === "number" && Number.isFinite(n) && n >= 0))))) return undefined;
  }
  for (const s of value.scenarios) {
    if (!record(s) || !["buy", "sell"].includes(String(s.side)) || sides.has(String(s.side))
      || !["market", "limit"].includes(String(s.order_type))
      || ![s.entry, s.stop_loss, s.take_profit, s.reward_risk].every(decimal)) return undefined;
    const entry = Number(s.entry), sl = Number(s.stop_loss), tp = Number(s.take_profit);
    if (s.side === "buy" ? !(sl < entry && entry < tp) : !(tp < entry && entry < sl)) return undefined;
    const ratio = Math.abs(tp - entry) / Math.abs(entry - sl);
    if (ratio < 2 - 1e-8 || Math.abs(ratio - Number(s.reward_risk)) > 0.01) return undefined;
    if (s.order_type === "limit" && !(s.side === "buy" ? entry < Number(value.bid) : entry > Number(value.ask))) return undefined;
    sides.add(String(s.side));
  }
  const roles = new Set<string>();
  for (const r of value.reports) {
    if (!record(r) || !["technical", "macro", "bull", "bear", "risk", "manager"].includes(String(r.role))
      || roles.has(String(r.role)) || !["buy", "sell", "wait"].includes(String(r.stance))
      || ![r.summary, r.counterargument, r.provider, r.model].every(v => typeof v === "string")
      || typeof r.veto !== "boolean" || !Array.isArray(r.evidence_refs)
      || !r.evidence_refs.every(v => typeof v === "string")) return undefined;
    roles.add(String(r.role));
    if (r.forecast != null && (!record(r.forecast) || !["up", "down", "range", "uncertain"].includes(String(r.forecast.direction))
      || !["5m", "1h", "4h", "1d"].includes(String(r.forecast.timeframe)) || r.forecast.horizon_bars !== 6
      || typeof r.forecast.rationale !== "string" || typeof r.forecast.invalidation !== "string")) return undefined;
  }
  if (value.unique_models !== new Set(value.reports.map(r => `${r.provider}:${r.model}`)).size) return undefined;
  if (value.failures != null && (!Array.isArray(value.failures) || !value.failures.every(r => record(r)
    && typeof r.role === "string" && typeof r.code === "string"))) return undefined;
  if (value.evidence != null && (!record(value.evidence) || !record(value.evidence.timeframes) || !record(value.evidence.macro)
    || typeof value.evidence.medium_term_price_context_ready !== "boolean"
    || !Object.values(value.evidence.timeframes).every(r => record(r) && typeof r.status === "string")
    || !Object.values(value.evidence.macro).every(r => record(r) && typeof r.status === "string"))) return undefined;
  if (value.status === "ready") {
    const risk = value.reports.find(r => r.role === "risk");
    const manager = value.reports.find(r => r.role === "manager");
    if ((Array.isArray(value.failures) && value.failures.length > 0) || sides.size !== 2 || roles.size !== 6 || value.recommendation === "wait"
      || risk?.veto || manager?.veto || risk?.stance === "wait" || manager?.stance !== value.recommendation) return undefined;
  } else if (value.recommendation !== "wait") return undefined;
  return value as unknown as ForexTradePlan;
}
