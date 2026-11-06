import type { ResearchObject } from "./research";

export const MAX_RESEARCH_BYTES = 1024 * 1024;
export type ForexResearchRequest = ResearchObject & {
  source: string; symbol: string; timeframe: string; dataset_revision: string;
  bars: ResearchObject[]; candidates: ResearchObject[]; round_trip_cost_bps: number;
};
export interface ForexResearchResult extends ResearchObject {
  status: string;
}
export interface ForexCostStressRequest extends ResearchObject {
  research: ForexResearchRequest;
  spread_bps: number; commission_bps: number; slippage_bps: number; gap_bps: number;
}
export interface ForexTradePathsRequest extends ResearchObject {
  research: ForexResearchRequest;
  seed: number; simulations: number; block_length: number;
}
export type ForexLabMethod = "walk_forward" | "cost_stress" | "trade_paths";
export type ForexLabRequest = ForexResearchRequest | ForexCostStressRequest | ForexTradePathsRequest;
export interface ForexExperimentSummary {
  id: string; created_at: string; attempt_count: number;
}
export interface ForexRunSummary {
  id: string; attempt: number; input_hash: string; status: string; created_at: string; finished_at: string | null;
}
export interface ForexExperimentList {
  experiments: ForexExperimentSummary[]; total: number; offset: number; limit: number;
}
export interface ForexExperimentDetail {
  id: string; created_at: string; attempt_count: number; runs: ForexRunSummary[]; offset: number; limit: number;
}
export interface ForexExperimentRun extends ForexRunSummary {
  experiment_id: string; request: ForexLabRequest; engine: ResearchObject; result: ForexResearchResult | null;
}

/** Only a bounded preview, never a second implementation of server validation. */
export function parseForexResearch(text: string): ForexResearchRequest {
  if (new TextEncoder().encode(text).byteLength > MAX_RESEARCH_BYTES) throw new Error("too_large");
  const data: unknown = JSON.parse(text);
  if (data === null || typeof data !== "object" || Array.isArray(data)) throw new Error("request_object");
  const row = data as ResearchObject;
  if (!Array.isArray(row.bars) || row.bars.length < 32 || row.bars.length > 2000
    || !Array.isArray(row.candidates) || row.candidates.length < 1 || row.candidates.length > 16
    || ["source", "symbol", "timeframe", "dataset_revision"].some((key) => typeof row[key] !== "string" || !row[key])
    || typeof row.round_trip_cost_bps !== "number" || !Number.isFinite(row.round_trip_cost_bps)) throw new Error("request_shape");
  return row as ForexResearchRequest;
}

export function parseForexCostStress(text: string): ForexCostStressRequest {
  if (new TextEncoder().encode(text).byteLength > MAX_RESEARCH_BYTES) throw new Error("too_large");
  const input = JSON.parse(text) as ForexCostStressRequest;
  if (input === null || typeof input !== "object" || Array.isArray(input)) throw new Error("request_object");
  parseForexResearch(JSON.stringify(input.research));
  if (["spread_bps", "commission_bps", "slippage_bps", "gap_bps"].some((key) => typeof input[key] !== "number" || !Number.isFinite(input[key]) || Number(input[key]) < 0)) throw new Error("request_shape");
  return input;
}

export function syntheticCostStressRequest(): ForexCostStressRequest {
  return { research: syntheticForexRequest(), spread_bps: 1, commission_bps: 0.5, slippage_bps: 0.5, gap_bps: 0 };
}

export function parseForexTradePaths(text: string): ForexTradePathsRequest {
  if (new TextEncoder().encode(text).byteLength > MAX_RESEARCH_BYTES) throw new Error("too_large");
  const input = JSON.parse(text) as ForexTradePathsRequest;
  if (input === null || typeof input !== "object" || Array.isArray(input)) throw new Error("request_object");
  parseForexResearch(JSON.stringify(input.research));
  for (const [name, minimum, maximum] of [["seed", 0, 4294967295], ["simulations", 100, 2000], ["block_length", 2, 64]] as const) {
    const value = input[name];
    if (typeof value !== "number" || !Number.isInteger(value) || value < minimum || value > maximum) throw new Error("request_shape");
  }
  return input;
}

export function parseForexLab(text: string, method: ForexLabMethod): ForexLabRequest {
  return method === "trade_paths" ? parseForexTradePaths(text) : method === "cost_stress" ? parseForexCostStress(text) : parseForexResearch(text);
}

export function forexLabMethod(request: ForexLabRequest): ForexLabMethod {
  return "simulations" in request && "block_length" in request ? "trade_paths" : "research" in request ? "cost_stress" : "walk_forward";
}

export function syntheticTradePathsRequest(): ForexTradePathsRequest {
  return { research: syntheticForexRequest(), seed: 42, simulations: 100, block_length: 2 };
}

/** Clearly labelled, deterministic synthetic bars. Loaded only on request. */
export function syntheticForexRequest(): ForexResearchRequest {
  const start = Date.parse("2025-01-06T00:00:00Z");
  const bars = Array.from({ length: 96 }, (_, index) => {
    const open = 100 + Math.sin(index * Math.PI / 6) * 4;
    const close = 100 + Math.sin((index + 1) * Math.PI / 6) * 4;
    return { time: new Date(start + index * 3600000).toISOString(), open, close,
      high: Math.max(open, close) + 0.5, low: Math.min(open, close) - 0.5, complete: true };
  });
  return { source: "synthetic_web_example_not_market_data", symbol: "XAUUSD", timeframe: "1h", price_basis: "mid",
    dataset_revision: "synthetic_web_example_v1", bars, candidates: [{ fast: 2, slow: 4 }, { fast: 3, slow: 6 }],
    n_blocks: 4, round_trip_cost_bps: 2, strategy: "sma_crossover" };
}
