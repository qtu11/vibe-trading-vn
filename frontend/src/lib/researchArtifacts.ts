import type { ResearchObject } from "./research";

export type ResearchKind = "vietnam" | "vietnam_comparables" | "vietnam_dcf" | "vietnam_reverse_dcf" | "crypto_basis";
export interface ResearchRevision {
  revision_id: string; parent_revision_id: string | null; kind: ResearchKind; created_at: string;
  scope: ResearchObject; request: ResearchObject; result: ResearchObject; hashes: ResearchObject; producer: ResearchObject;
  content_scope: string; verification_status: string; review_state: string; review_history: ResearchObject[]; limitations: string[];
}
export interface ResearchRevisionList {
  items: Pick<ResearchRevision, "revision_id" | "parent_revision_id" | "kind" | "created_at" | "scope" | "review_state">[];
  total: number; next_offset: number | null;
}

export interface ResearchAttempt {
  attempt_id: string; kind: ResearchKind; parent_revision_id: string | null; idempotency_key: string | null;
  status: "succeeded" | "failed" | "in_flight_unknown"; created_at: string; finished_at: string | null;
  revision_id: string | null; error: { code: string; message: string } | null;
}
export interface ResearchAttemptList {
  items: ResearchAttempt[]; total: number; next_offset: number | null;
  refresh_state: { state: "no_refresh_attempt" | "refresh_failed" | "refresh_in_flight_unknown" | "superseded";
    parent_revision_id: string; last_attempt: ResearchAttempt | null; last_good_revision_id: string } | null;
}
