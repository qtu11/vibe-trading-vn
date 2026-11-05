/**
 * Live per-attempt LLM token counter, fed by the `llm_usage` SSE event.
 *
 * The backend emits one `llm_usage` event per agent iteration carrying the
 * provider-reported usage DELTA plus `iter` and `attempt_id`
 * (emitted at agent/src/agent/loop.py; `attempt_id` injected at
 * agent/src/session/service.py). useSSE dedups by Last-Event-ID, but a
 * reconnect replay can still deliver an already-applied iteration, so
 * accumulation is keyed idempotently on `(attemptId, iter)` and a new
 * attempt_id resets the running totals to zero.
 */

import { useCallback, useRef, useState } from "react";

/** Loose SSE payload accepted at the accumulation boundary (untrusted data). */
export type UsageDelta = Readonly<Record<string, unknown>>;

export interface LlmUsageTotals {
  input: number;
  output: number;
  calls: number;
  cached: number;
  cacheReportedCalls: number;
  missingCalls: number;
}

export interface LlmUsageCounter extends LlmUsageTotals {
  record: (attemptId: string, iter: number, delta: UsageDelta) => void;
  reset: () => void;
}

const ZERO: LlmUsageTotals = { input: 0, output: 0, calls: 0, cached: 0, cacheReportedCalls: 0, missingCalls: 0 };

/** Missing / null / non-finite / negative provider fields count as 0 — never NaN. */
function toTokenCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

export function useLlmUsageCounter(): LlmUsageCounter {
  // The ref owns the truth so records batched before a re-render still
  // accumulate independently; state only mirrors it for rendering.
  const totalsRef = useRef<LlmUsageTotals>({ ...ZERO });
  const attemptRef = useRef<string | null>(null);
  const seenKeysRef = useRef<Set<string>>(new Set());
  const [totals, setTotals] = useState<LlmUsageTotals>(totalsRef.current);

  const commit = useCallback((): void => {
    setTotals({ ...totalsRef.current });
  }, []);

  const record = useCallback((attemptId: string, iter: number, delta: UsageDelta): void => {
    if (attemptRef.current !== attemptId) {
      attemptRef.current = attemptId;
      seenKeysRef.current.clear();
      totalsRef.current = { ...ZERO };
    }
    const call = toTokenCount(delta.usage_event_index) || toTokenCount(delta.call_index);
    const purpose = typeof delta.purpose === "string" ? delta.purpose : "main";
    const key = `${attemptId}:${delta.unavailable === true ? "unreported:" : ""}${call > 0 ? `call:${call}` : `iter:${iter}:${purpose}`}`;
    if (seenKeysRef.current.has(key)) return;
    seenKeysRef.current.add(key);
    const prev = totalsRef.current;
    totalsRef.current = {
      input: prev.input + toTokenCount(delta.input_tokens),
      output: prev.output + toTokenCount(delta.output_tokens),
      calls: prev.calls + 1,
      cached: prev.cached + Math.min(toTokenCount(delta.cache_read_tokens), toTokenCount(delta.input_tokens)),
      cacheReportedCalls: prev.cacheReportedCalls + (typeof delta.cache_read_tokens === "number" && Number.isFinite(delta.cache_read_tokens) && delta.cache_read_tokens >= 0 ? 1 : 0),
      missingCalls: prev.missingCalls + (delta.unavailable === true ? 1 : 0),
    };
    commit();
  }, [commit]);

  const reset = useCallback((): void => {
    attemptRef.current = null;
    seenKeysRef.current.clear();
    totalsRef.current = { ...ZERO };
    commit();
  }, [commit]);

  return { ...totals, record, reset };
}
