/** Read-only research envelopes. Financial decimals stay strings end to end. */
export type ResearchValue = string | number | boolean | null | ResearchValue[] | { [key: string]: ResearchValue };
export type ResearchObject = { [key: string]: ResearchValue };
export interface VietnamRequest {
  code: string;
  as_of?: string;
  period: "quarter" | "annual";
  consolidation: "consolidated" | "separate";
  offset: number;
}
export interface CryptoRequest {
  symbol: string;
  metric: "open_interest" | "funding";
  period: string;
  limit: number;
  mode?: "live" | "archive";
  as_of?: string;
}
export interface ResearchResult {
  ok: boolean;
  error?: string;
  error_code?: string;
  data?: Record<string, ResearchObject>;
  paging?: { total: number; offset: number; returned: number; next_offset: number | null; complete: boolean };
  symbol?: string;
  metric?: string;
  summary?: ResearchObject;
  provenance?: ResearchObject;
  coverage?: ResearchObject;
  units?: ResearchObject;
  display?: ResearchObject;
  observations?: ResearchObject[];
  limitations?: string[];
  archive?: ResearchObject;
}

export function object(value: ResearchValue | undefined): ResearchObject {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
}

/** Untrusted URLs must never become executable anchors, even on a local source. */
export function evidenceUrl(value: ResearchValue | undefined): string | undefined {
  if (typeof value !== "string") return undefined;
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : undefined;
  } catch { return undefined; }
}
