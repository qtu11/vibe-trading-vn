/**
 * Reply metadata citations from the backend grounding ledger.
 *
 * The ledger is authoritative: a source only appears here after a tool
 * returned a page-shaped result, and a `[S#]` marker in the answer is only
 * accepted when that id resolves to one of these records. Everything is
 * parsed defensively because this metadata crosses a persisted JSON boundary.
 */
export interface SourceCitation {
  sourceId: string;
  title: string;
  url: string | null;
  domain: string | null;
  publisher: string | null;
  tier: number;
  tierLabel: string;
  market: string[];
  publishedAt: string | null;
  dataEffectiveAt: string | null;
  dataEffectiveBasis: "explicit" | "published_at" | null;
  retrievedAt: string | null;
  verification: string;
  citeAllowed: boolean;
}

const MAX_SOURCES = 40;
const MAX_TEXT = 400;

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown, limit = MAX_TEXT): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, limit) : null;
}

function safeHref(value: unknown): string | null {
  const url = text(value, 2_000);
  return url && /^https?:\/\//i.test(url) ? url : null;
}

function timestamp(value: unknown): string | null {
  return text(value, 80);
}

function tierOf(value: unknown): number {
  return typeof value === "number"
    && Number.isInteger(value)
    && value >= 1
    && value <= 5
    ? value
    : 5;
}

/** Parse the backend `sources` reply field, dropping malformed rows. */
export function parseSourceCitations(value: unknown): SourceCitation[] {
  if (!Array.isArray(value)) return [];
  const sources: SourceCitation[] = [];
  const seen = new Set<string>();
  for (const item of value.slice(0, MAX_SOURCES)) {
    if (!record(item)) continue;
    const sourceId = text(item.source_id, 20);
    const title = text(item.title);
    if (!sourceId || !title || seen.has(sourceId)) continue;
    seen.add(sourceId);
    const basis = text(item.data_effective_basis, 20);
    sources.push({
      sourceId,
      title,
      url: safeHref(item.url),
      domain: text(item.domain, 200),
      publisher: text(item.publisher, 200),
      tier: tierOf(item.tier),
      tierLabel: text(item.tier_label, 80) ?? `Tier ${tierOf(item.tier)}`,
      market: Array.isArray(item.market)
        ? item.market
            .map((entry) => text(entry, 40))
            .filter((entry): entry is string => entry !== null)
            .slice(0, 4)
        : [],
      publishedAt: timestamp(item.published_at),
      dataEffectiveAt: timestamp(item.data_effective_at),
      dataEffectiveBasis:
        basis === "explicit" || basis === "published_at" ? basis : null,
      retrievedAt: timestamp(item.retrieved_at),
      verification: text(item.verification, 40) ?? "unverified",
      citeAllowed: item.cite_allowed !== false,
    });
  }
  return sources;
}
