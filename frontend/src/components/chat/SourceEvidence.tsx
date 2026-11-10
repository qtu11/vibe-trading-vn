import { memo } from "react";
import { ExternalLink } from "lucide-react";
import type { SourceCitation } from "@/lib/sourceEvidence";
import { SourceLink } from "./SourceLink";

function stripProtocol(value: string): string {
  return value.replace(/^https?:\/\//i, "").replace(/\/$/, "");
}

function SourceRow({ source }: { source: SourceCitation }) {
  const times = [
    source.publishedAt ? `published ${source.publishedAt}` : null,
    source.dataEffectiveAt
      ? `data effective ${source.dataEffectiveAt}${
          source.dataEffectiveBasis === "published_at"
            ? " (publication fallback)"
            : ""
        }`
      : null,
    source.retrievedAt ? `retrieved ${source.retrievedAt}` : null,
  ].filter((part): part is string => part !== null);
  const provider = [source.publisher, source.domain ?? (source.url ? stripProtocol(source.url) : null)]
    .filter((part, index, all): part is string => Boolean(part) && all.indexOf(part) === index)
    .join(" · ");
  const markets = source.market.length > 0 ? source.market.join(", ") : null;

  return (
    <li className="rounded-md border border-border/40 bg-background/40 px-2 py-1.5 has-[[aria-current=page]]:border-primary has-[[aria-current=page]]:bg-primary/5">
      <div className="flex items-start gap-2">
        <span className="mt-px shrink-0 rounded bg-muted px-1 py-0.5 font-mono text-[10px] leading-none text-muted-foreground">
          {source.sourceId}
        </span>
        <div className="min-w-0 flex-1 space-y-0.5">
          <div className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
            {source.url ? (
              <SourceLink
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex min-w-0 items-center gap-1 text-xs font-medium text-foreground underline decoration-border underline-offset-2 hover:text-primary"
              >
                <span className="truncate">{source.title}</span>
                <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />
              </SourceLink>
            ) : (
              <span className="text-xs font-medium text-foreground">{source.title}</span>
            )}
            <span className="rounded border border-border/60 px-1 py-0.5 text-[10px] text-muted-foreground">
              Tier {source.tier} · {source.tierLabel}
            </span>
            <span
              className={
                source.verification === "unverified"
                  ? "rounded border border-warning/40 bg-warning/5 px-1 py-0.5 text-[10px] text-warning"
                  : "rounded border border-success/40 bg-success/5 px-1 py-0.5 text-[10px] text-success"
              }
            >
              {source.verification}
            </span>
            {!source.citeAllowed && (
              <span className="rounded border border-danger/40 bg-danger/5 px-1 py-0.5 text-[10px] text-danger">
                citation not allowed
              </span>
            )}
          </div>
          {(provider || markets) && (
            <p className="truncate text-[10px] text-muted-foreground">
              {[provider || null, markets].filter(Boolean).join(" · ")}
            </p>
          )}
          {times.length > 0 && (
            <p className="text-[10px] leading-snug text-muted-foreground">
              {times.join(" · ")}
            </p>
          )}
        </div>
      </div>
    </li>
  );
}

/**
 * The human-readable half of the citation contract.
 *
 * `[S#]` markers in the answer resolve here. The ledger labels every page
 * `unverified` because the publisher saying a number is not independent
 * confirmation of it; the tier and timestamps let a reader judge that.
 */
export const SourceEvidence = memo(function SourceEvidence({
  sources,
}: {
  sources: SourceCitation[];
}) {
  if (sources.length === 0) return null;
  return (
    <details className="group/sources rounded-lg border border-border/50 bg-muted/20 px-3 py-2">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        <span>Sources · Nguồn</span>
        <span className="rounded-full bg-muted px-1.5 py-0.5 font-mono text-[10px] normal-case tracking-normal">
          {sources.length}
        </span>
        <span className="ms-auto font-normal normal-case tracking-normal text-muted-foreground/70 group-open/sources:hidden">
          [S#] markers resolve here
        </span>
      </summary>
      <ul className="mt-2 space-y-1">
        {sources.map((source) => (
          <SourceRow key={source.sourceId} source={source} />
        ))}
      </ul>
    </details>
  );
});

export default SourceEvidence;
