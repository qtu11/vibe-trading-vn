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
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return ["http:", "https:"].includes(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : null;
  } catch { return null; }
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

function markdownText(value: string): string {
  return value.replace(/[\r\n\t]+/g, " ").replace(/[\\`*_{}\[\]<>()#!|]/g, "\\$&");
}

function markdownUrl(value: string): string {
  return value.replace(/[()<>"\s\\]/g, (char) => encodeURIComponent(char).replace(/\(/g, "%28").replace(/\)/g, "%29"));
}

function apaDate(value: string | null): string {
  if (!value) return "n.d.";
  if (/^\d{4}$/.test(value)) return value;
  const match = /^(\d{4})-(\d{2})(?:-(\d{2})(?:T.*)?)?$/.exec(value);
  if (!match) return "n.d.";
  const date = new Date(`${match[1]}-${match[2]}-${match[3] || "01"}T00:00:00Z`);
  if (!Number.isFinite(date.getTime()) || date.getUTCMonth() + 1 !== Number(match[2]) || date.getUTCDate() !== Number(match[3] || 1)) return "n.d.";
  return `${match[1]}, ${date.toLocaleString("en-US", { month: "long", timeZone: "UTC" })}${match[3] ? ` ${Number(match[3])}` : ""}`;
}

/** Keep each turn's S# mapping: IDs may be reused by subsequent research runs. */
export function sourceResolutionMarkdown(sources: SourceCitation[]): string {
  return sources.filter((source) => source.citeAllowed && safeHref(source.url))
    .map((source) => `[${markdownText(source.sourceId)}](${markdownUrl(source.url!)})`).join(" · ");
}

export function sourceReferencesMarkdown(sources: SourceCitation[]): string {
  const unique = new Map<string, SourceCitation>();
  for (const source of sources) {
    const url = safeHref(source.url);
    if (source.citeAllowed && url && !unique.has(url)) unique.set(url, source);
  }
  if (!unique.size) return "";
  const entries = [...unique.values()].sort((a, b) => a.title.localeCompare(b.title, "en"));
  return ["## Tài liệu tham khảo (APA 7th)", "",
    "Metadata chưa có tác giả: dùng nhan đề ở vị trí tác giả; n.d. khi thiếu ngày xuất bản. Trạng thái nguồn không được nâng thành đã xác minh khi xuất.", "",
    ...entries.flatMap((source) => [
      `*${markdownText(source.title)}*${/[.!?]$/.test(source.title) ? "" : "."} (${apaDate(source.publishedAt)}).${source.publisher ? ` ${markdownText(source.publisher)}.` : ""} [${markdownText(source.url!)}](${markdownUrl(source.url!)})`, "",
    ]),
  ].join("\n");
}
