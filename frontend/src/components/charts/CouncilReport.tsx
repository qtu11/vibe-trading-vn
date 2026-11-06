import { memo, useMemo, type ReactNode } from "react";
import { CandlestickChart } from "./CandlestickChart";
import { parsePriceChartSpec, toPriceBars } from "./ChartBlock";
import type { PriceBar } from "@/lib/api";

/** One self-reported source in the council verdict. */
export interface CouncilSource {
  ref?: string | null;
  title?: string | null;
  url?: string | null;
  publisher?: string | null;
  published_at?: string | null;
  tier?: string | null;
  verification?: string | null;
}

interface PriceRange {
  low: number;
  high: number;
}

export interface CouncilVerdict {
  stance?: string | null;
  stance_label?: string | null;
  horizon?: string | null;
  confidence_pct?: number | null;
  fair_value?: PriceRange | null;
  entry_zone?: PriceRange | null;
  stop?: number | null;
  position_cap_pct?: number | null;
  catalysts?: string[];
  risks?: string[];
  invalidation?: string | null;
  sources?: CouncilSource[];
  verification?: string | null;
}

interface CouncilSizingBucket {
  risk_pct?: number;
  risk_budget?: number;
  shares?: number;
  position_value?: number;
}

export interface CouncilEvaluation {
  price_scale?: number | null;
  price_scale_note?: string | null;
  entry_mid?: number | null;
  risk_per_share?: number | null;
  reward_per_share?: number | null;
  risk_reward?: number | null;
  stop_distance_pct?: number | null;
  observed_window?: Record<string, unknown> | null;
  sizing?: {
    available?: boolean;
    currency?: string | null;
    lot_size?: number | null;
    risk_1pct?: CouncilSizingBucket | null;
    risk_2pct?: CouncilSizingBucket | null;
    position_cap?: { cap_pct?: number; shares?: number; position_value?: number } | null;
    binding?: string | null;
    note?: string | null;
  } | null;
}

export interface CouncilDebateEntry {
  id?: string | null;
  agent_id?: string | null;
  role?: string | null;
  status?: string | null;
  summary?: string | null;
  error?: string | null;
}

export interface CouncilIssue {
  code?: string | null;
  severity?: string | null;
  message?: string | null;
}

export interface CouncilSnapshot {
  symbol?: string | null;
  source?: string | null;
  currency?: string | null;
  adjustment?: string | null;
  as_of?: string | null;
  bars?: number | null;
  last_close?: number | null;
  window_low?: number | null;
  window_low_date?: string | null;
  window_high?: number | null;
  window_high_date?: string | null;
}

/** The `council` fenced-block contract. Unknown fields are ignored. */
export interface CouncilBlock {
  type: "council";
  version?: number | null;
  symbol: string;
  generated_at?: string | null;
  snapshot?: CouncilSnapshot | null;
  chart?: unknown;
  verdict?: CouncilVerdict | null;
  evaluation?: CouncilEvaluation | null;
  issues?: CouncilIssue[];
  actionable?: boolean;
  trade_actionable?: boolean;
  blocked_reason?: string | null;
  debate?: CouncilDebateEntry[];
  pm_report?: string | null;
  sources?: CouncilSource[];
  disclaimer?: string | null;
}

const MAX_DEBATE_ENTRIES = 8;
const MAX_ISSUES = 8;
const MAX_SOURCES = 20;

const numberFormat = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function textOf(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatNumber(value: number | null | undefined): string | null {
  return typeof value === "number" && Number.isFinite(value)
    ? numberFormat.format(value)
    : null;
}

function formatRange(range: PriceRange | null | undefined): string | null {
  if (!range) return null;
  const low = formatNumber(range.low);
  const high = formatNumber(range.high);
  if (!low || !high) return null;
  return low === high ? low : `${low} – ${high}`;
}

function safeHref(value: unknown): string | null {
  const url = textOf(value);
  if (!url) return null;
  return /^https?:\/\//i.test(url) ? url : null;
}

function parseRange(value: unknown): PriceRange | null {
  if (!isRecord(value)) return null;
  const low = finiteNumber(value.low);
  const high = finiteNumber(value.high);
  if (low === null || high === null) return null;
  return { low, high };
}

function parseSources(value: unknown): CouncilSource[] {
  if (!Array.isArray(value)) return [];
  const sources: CouncilSource[] = [];
  for (const item of value.slice(0, MAX_SOURCES)) {
    if (!isRecord(item)) continue;
    const source: CouncilSource = {
      ref: textOf(item.ref),
      title: textOf(item.title),
      url: safeHref(item.url),
      publisher: textOf(item.publisher),
      published_at: textOf(item.published_at),
      tier: textOf(item.tier),
      verification: textOf(item.verification),
    };
    if (source.title || source.url || source.ref) sources.push(source);
  }
  return sources;
}

export function parseCouncilBlock(text: string): CouncilBlock | null {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return null;
  }
  if (!isRecord(raw)) return null;
  if (textOf(raw.type)?.toLowerCase() !== "council") return null;
  const symbol = textOf(raw.symbol);
  if (!symbol) return null;

  const verdictRaw = raw.verdict;
  let verdict: CouncilVerdict | null = null;
  if (verdictRaw !== null && verdictRaw !== undefined) {
    if (!isRecord(verdictRaw)) return null;
    verdict = {
      stance: textOf(verdictRaw.stance),
      stance_label: textOf(verdictRaw.stance_label),
      horizon: textOf(verdictRaw.horizon),
      confidence_pct: finiteNumber(verdictRaw.confidence_pct),
      fair_value: parseRange(verdictRaw.fair_value),
      entry_zone: parseRange(verdictRaw.entry_zone),
      stop: finiteNumber(verdictRaw.stop),
      position_cap_pct: finiteNumber(verdictRaw.position_cap_pct),
      catalysts: parseStrings(verdictRaw.catalysts),
      risks: parseStrings(verdictRaw.risks),
      invalidation: textOf(verdictRaw.invalidation),
      sources: parseSources(verdictRaw.sources),
      verification: textOf(verdictRaw.verification),
    };
  }

  const snapshotRaw = isRecord(raw.snapshot) ? raw.snapshot : null;
  const evaluationRaw = isRecord(raw.evaluation) ? raw.evaluation : null;
  const debate = parseDebate(raw.debate);
  const issues: CouncilIssue[] = [];
  if (Array.isArray(raw.issues)) {
    for (const item of raw.issues.slice(0, MAX_ISSUES)) {
      if (!isRecord(item)) continue;
      issues.push({
        code: textOf(item.code),
        severity: textOf(item.severity),
        message: textOf(item.message),
      });
    }
  }

  return {
    type: "council",
    version: finiteNumber(raw.version),
    symbol,
    generated_at: textOf(raw.generated_at),
    snapshot: snapshotRaw
      ? {
          symbol: textOf(snapshotRaw.symbol),
          source: textOf(snapshotRaw.source),
          currency: textOf(snapshotRaw.currency),
          adjustment: textOf(snapshotRaw.adjustment),
          as_of: textOf(snapshotRaw.as_of),
          bars: finiteNumber(snapshotRaw.bars),
          last_close: finiteNumber(snapshotRaw.last_close),
          window_low: finiteNumber(snapshotRaw.window_low),
          window_low_date: textOf(snapshotRaw.window_low_date),
          window_high: finiteNumber(snapshotRaw.window_high),
          window_high_date: textOf(snapshotRaw.window_high_date),
        }
      : null,
    chart: raw.chart,
    verdict,
    evaluation: evaluationRaw
      ? {
          price_scale: finiteNumber(evaluationRaw.price_scale),
          price_scale_note: textOf(evaluationRaw.price_scale_note),
          entry_mid: finiteNumber(evaluationRaw.entry_mid),
          risk_per_share: finiteNumber(evaluationRaw.risk_per_share),
          reward_per_share: finiteNumber(evaluationRaw.reward_per_share),
          risk_reward: finiteNumber(evaluationRaw.risk_reward),
          stop_distance_pct: finiteNumber(evaluationRaw.stop_distance_pct),
          observed_window: isRecord(evaluationRaw.observed_window)
            ? evaluationRaw.observed_window
            : null,
          sizing: isRecord(evaluationRaw.sizing)
            ? {
                available: evaluationRaw.sizing.available === true,
                currency: textOf(evaluationRaw.sizing.currency),
                lot_size: finiteNumber(evaluationRaw.sizing.lot_size),
                risk_1pct: parseSizingBucket(evaluationRaw.sizing.risk_1pct),
                risk_2pct: parseSizingBucket(evaluationRaw.sizing.risk_2pct),
                position_cap: isRecord(evaluationRaw.sizing.position_cap)
                  ? {
                      cap_pct: finiteNumber(evaluationRaw.sizing.position_cap.cap_pct) ?? undefined,
                      shares: finiteNumber(evaluationRaw.sizing.position_cap.shares) ?? undefined,
                      position_value:
                        finiteNumber(evaluationRaw.sizing.position_cap.position_value) ?? undefined,
                    }
                  : null,
                binding: textOf(evaluationRaw.sizing.binding),
                note: textOf(evaluationRaw.sizing.note),
              }
            : null,
        }
      : null,
    issues,
    actionable: raw.actionable === true,
    trade_actionable: raw.trade_actionable === true,
    blocked_reason: textOf(raw.blocked_reason),
    debate,
    pm_report: textOf(raw.pm_report),
    sources: parseSources(raw.sources),
    disclaimer: textOf(raw.disclaimer),
  };
}

function parseStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => textOf(item))
    .filter((item): item is string => item !== null)
    .slice(0, 20);
}

function parseSizingBucket(value: unknown): CouncilSizingBucket | null {
  if (!isRecord(value)) return null;
  return {
    risk_pct: finiteNumber(value.risk_pct) ?? undefined,
    risk_budget: finiteNumber(value.risk_budget) ?? undefined,
    shares: finiteNumber(value.shares) ?? undefined,
    position_value: finiteNumber(value.position_value) ?? undefined,
  };
}

function parseDebate(value: unknown): CouncilDebateEntry[] {
  if (!Array.isArray(value)) return [];
  const entries: CouncilDebateEntry[] = [];
  for (const item of value.slice(0, MAX_DEBATE_ENTRIES)) {
    if (!isRecord(item)) continue;
    entries.push({
      id: textOf(item.id),
      agent_id: textOf(item.agent_id),
      role: textOf(item.role),
      status: textOf(item.status),
      summary: textOf(item.summary),
      error: textOf(item.error),
    });
  }
  return entries;
}

const STANCE_STYLES: Record<string, string> = {
  buy: "border-success/40 bg-success/5 text-success",
  add: "border-success/40 bg-success/5 text-success",
  sell: "border-danger/40 bg-danger/5 text-danger",
  avoid: "border-danger/40 bg-danger/5 text-danger",
  hold: "border-border/60 bg-muted/30 text-foreground",
  wait: "border-border/60 bg-muted/30 text-muted-foreground",
};

function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-border/50 bg-background/40 px-3 py-2">
      <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      {children}
    </section>
  );
}

function KeyValue({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className="flex items-baseline justify-between gap-2 text-xs">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="text-end font-mono tabular-nums">{value}</span>
    </div>
  );
}

function SourceList({ sources }: { sources: CouncilSource[] }) {
  if (sources.length === 0) {
    return <p className="text-xs text-muted-foreground">No source was named.</p>;
  }
  return (
    <ul className="space-y-1.5">
      {sources.map((source, index) => (
        <li key={`${source.ref ?? "source"}-${index}`} className="text-xs leading-snug">
          <div className="flex flex-wrap items-baseline gap-1.5">
            {source.ref && (
              <span className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">
                {source.ref}
              </span>
            )}
            {source.url ? (
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-foreground underline decoration-border underline-offset-2 hover:text-primary"
              >
                {source.title ?? source.url}
              </a>
            ) : (
              <span className="text-foreground">{source.title ?? "Untitled"}</span>
            )}
            {source.tier && (
              <span className="rounded border border-border/60 px-1 py-0.5 text-[10px] text-muted-foreground">
                {source.tier}
              </span>
            )}
            {source.verification && (
              <span className="rounded border border-warning/40 bg-warning/5 px-1 py-0.5 text-[10px] text-warning">
                {source.verification}
              </span>
            )}
          </div>
          <div className="text-[10px] text-muted-foreground">
            {[source.publisher, source.published_at]
              .filter((part): part is string => Boolean(part))
              .join(" · ")}
          </div>
        </li>
      ))}
    </ul>
  );
}

export const CouncilReport = memo(function CouncilReport({ code }: { code: string }) {
  const block = useMemo(() => parseCouncilBlock(code), [code]);
  const chart = useMemo(() => {
    if (!block?.chart) return null;
    try {
      return parsePriceChartSpec(JSON.stringify(block.chart));
    } catch {
      return null;
    }
  }, [block]);
  const bars = useMemo<PriceBar[]>(
    () => (chart ? toPriceBars(chart) : []),
    [chart],
  );

  if (!block) {
    return (
      <pre className="overflow-x-auto rounded-lg border border-border/50 bg-muted/30 p-3 text-[11px] leading-relaxed">
        <code>{code}</code>
      </pre>
    );
  }

  const verdict = block.verdict;
  const stanceKey = (verdict?.stance ?? "").toLowerCase();
  const stanceStyle = STANCE_STYLES[stanceKey] ?? "border-border/60 bg-muted/30";
  const stanceLabel = verdict?.stance_label ?? verdict?.stance ?? "NO VERDICT";
  const snapshot = block.snapshot;
  const evaluation = block.evaluation;
  const sizing = evaluation?.sizing;
  const sources = block.sources?.length ? block.sources : verdict?.sources ?? [];
  const bull = block.debate?.find((entry) => entry.agent_id === "bull_advocate");
  const bear = block.debate?.find((entry) => entry.agent_id === "bear_advocate");
  const others = block.debate?.filter(
    (entry) =>
      entry.agent_id !== "bull_advocate" && entry.agent_id !== "bear_advocate",
  ) ?? [];
  const meta = [
    snapshot?.source,
    snapshot?.currency,
    snapshot?.as_of ? `as of ${snapshot.as_of}` : null,
    snapshot?.bars ? `${snapshot.bars} bars` : null,
    snapshot?.adjustment,
  ].filter((part): part is string => Boolean(part));

  return (
    <figure
      dir="ltr"
      className="my-3 space-y-2 overflow-hidden rounded-xl border border-border/60 bg-card/40 p-3"
    >
      <figcaption className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-mono text-xs font-semibold">{block.symbol}</span>
        <span className="text-[10px] text-muted-foreground">{meta.join(" · ")}</span>
        {block.generated_at && (
          <span className="ms-auto text-[10px] text-muted-foreground">
            {block.generated_at}
          </span>
        )}
      </figcaption>

      <div className={`rounded-lg border px-3 py-2 ${stanceStyle}`}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold">{stanceLabel}</span>
          {verdict?.horizon && (
            <span className="text-[10px] opacity-80">{verdict.horizon}</span>
          )}
          {verdict?.confidence_pct != null && (
            <span className="text-[10px] opacity-80">
              {Math.round(verdict.confidence_pct)}% confidence
            </span>
          )}
          <span className="ms-auto text-[10px] opacity-80">
            {block.trade_actionable
              ? "trade-actionable"
              : block.actionable
                ? "actionable"
                : "not actionable"}
          </span>
        </div>
        {!block.actionable && (
          <p className="mt-1 text-[11px] opacity-90">
            {block.blocked_reason
              ? `Blocked: ${block.blocked_reason}`
              : "The council did not provide evidence sufficient for advice."}
          </p>
        )}
      </div>

      <div className="grid gap-2 md:grid-cols-2">
        <Section title="Bull case">
          {bull?.summary ? (
            <p className="whitespace-pre-wrap text-xs leading-relaxed">{bull.summary}</p>
          ) : (
            <p className="text-xs text-muted-foreground">No bull summary.</p>
          )}
        </Section>
        <Section title="Bear case">
          {bear?.summary ? (
            <p className="whitespace-pre-wrap text-xs leading-relaxed">{bear.summary}</p>
          ) : (
            <p className="text-xs text-muted-foreground">No bear summary.</p>
          )}
        </Section>
      </div>

      {others.length > 0 && (
        <Section title="Other inputs">
          <ul className="space-y-1">
            {others.map((entry, index) => (
              <li key={`${entry.agent_id ?? "role"}-${index}`} className="text-xs leading-snug">
                <span className="font-medium">{entry.role ?? entry.agent_id ?? "Agent"}</span>
                {entry.error ? (
                  <span className="text-danger"> — {entry.error}</span>
                ) : (
                  <span className="text-muted-foreground">
                    {" — "}
                    {entry.summary ?? entry.status ?? "no summary"}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <div className="grid gap-2 md:grid-cols-3">
        <Section title="Facts · Dữ kiện">
          <div className="space-y-1">
            <KeyValue label="Last close" value={formatNumber(snapshot?.last_close)} />
            <KeyValue label="Window low" value={formatNumber(snapshot?.window_low)} />
            <KeyValue label="Window high" value={formatNumber(snapshot?.window_high)} />
            <KeyValue
              label="Window"
              value={
                snapshot?.window_low_date && snapshot?.window_high_date
                  ? `${snapshot.window_low_date} → ${snapshot.window_high_date}`
                  : null
              }
            />
          </div>
        </Section>

        <Section title="Evaluation · Đánh giá">
          <div className="space-y-1">
            <KeyValue label="Entry mid" value={formatNumber(evaluation?.entry_mid)} />
            <KeyValue
              label="Risk / share"
              value={formatNumber(evaluation?.risk_per_share)}
            />
            <KeyValue label="R / R" value={formatNumber(evaluation?.risk_reward)} />
            <KeyValue
              label="Stop distance"
              value={
                evaluation?.stop_distance_pct != null
                  ? `${formatNumber(evaluation.stop_distance_pct)}%`
                  : null
              }
            />
            <KeyValue
              label="Price scale"
              value={
                evaluation?.price_scale != null && evaluation.price_scale !== 1
                  ? `${formatNumber(evaluation.price_scale)}×`
                  : null
              }
            />
            {sizing?.binding && <KeyValue label="Sizing binding" value={sizing.binding} />}
            {sizing?.risk_1pct?.shares != null && (
              <KeyValue
                label="Shares @1% risk"
                value={formatNumber(sizing.risk_1pct.shares)}
              />
            )}
            {sizing?.position_cap?.shares != null && (
              <KeyValue
                label="Shares @cap"
                value={formatNumber(sizing.position_cap.shares)}
              />
            )}
          </div>
          {block.issues && block.issues.length > 0 && (
            <ul className="mt-1.5 space-y-0.5">
              {block.issues.map((issue, index) => (
                <li
                  key={`${issue.code ?? "issue"}-${index}`}
                  className={
                    issue.severity === "warning"
                      ? "text-[10px] text-warning"
                      : "text-[10px] text-danger"
                  }
                >
                  {issue.code ?? "issue"}
                  {issue.message ? `: ${issue.message}` : ""}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Advice · Lời khuyên">
          <div className="space-y-1">
            <KeyValue label="Entry zone" value={formatRange(verdict?.entry_zone)} />
            <KeyValue label="Stop" value={formatNumber(verdict?.stop)} />
            <KeyValue label="Fair value" value={formatRange(verdict?.fair_value)} />
            <KeyValue
              label="Position cap"
              value={
                verdict?.position_cap_pct != null
                  ? `${formatNumber(verdict.position_cap_pct)}% NAV`
                  : null
              }
            />
          </div>
          {verdict?.catalysts && verdict.catalysts.length > 0 && (
            <p className="mt-1.5 text-[11px] leading-snug">
              <span className="text-muted-foreground">Catalysts: </span>
              {verdict.catalysts.join("; ")}
            </p>
          )}
          {verdict?.risks && verdict.risks.length > 0 && (
            <p className="mt-1 text-[11px] leading-snug">
              <span className="text-muted-foreground">Risks: </span>
              {verdict.risks.join("; ")}
            </p>
          )}
          {verdict?.invalidation && (
            <p className="mt-1 text-[11px] leading-snug">
              <span className="text-muted-foreground">Invalidation: </span>
              {verdict.invalidation}
            </p>
          )}
        </Section>
      </div>

      <Section title="Sources · Nguồn (council-reported, unverified)">
        <SourceList sources={sources} />
      </Section>

      {chart && bars.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-border/50">
          <div className="truncate border-b border-border/50 px-2 py-1 font-mono text-[10px] text-muted-foreground">
            {[chart.symbol, chart.currency, chart.as_of, chart.source]
              .filter((part): part is string => Boolean(part))
              .join(" · ")}
          </div>
          <CandlestickChart data={bars} height={300} />
        </div>
      )}

      {block.pm_report && (
        <details className="rounded-lg border border-border/50 bg-background/40 px-3 py-2">
          <summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            PM report
          </summary>
          <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed">
            {block.pm_report}
          </p>
        </details>
      )}

      {block.disclaimer && (
        <p className="text-[10px] leading-snug text-muted-foreground">{block.disclaimer}</p>
      )}
    </figure>
  );
});

export default CouncilReport;
