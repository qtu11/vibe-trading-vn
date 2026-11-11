import { Search, ExternalLink } from "lucide-react";
import { useId } from "react";
import { MarkdownContent } from "./MessageBubble";
import { SourceLink } from "./SourceLink";
import { cn } from "@/lib/utils";
import { useReportPreviewStore, type ResearchSource } from "@/stores/reportPreview";

/**
 * The research-results mode of the research pane.
 *
 * A web search ran, the agent read the pages it found and wrote a synthesis.
 * That synthesis and its sources were only ever visible as a 200-character
 * tool preview in the chat timeline, so the user could not read it without
 * digging through the run log. This panel puts it next to the document it
 * supports.
 */
export function ResearchPreviewPanel({ tabId }: { tabId?: string }) {
  const tab = useReportPreviewStore((state) => state.tabs.find((item) => item.id === (tabId ?? state.activeId)) ?? null);
  const titleId = useId();
  if (!tab || tab.kind !== "research" || tab.selection.kind !== "research") return null;
  const research = tab.selection.research;
  const sources: ResearchSource[] = research.sources ?? [];

  return (
    <aside aria-labelledby={titleId} className="flex h-full min-h-0 w-full flex-col bg-surface-base">
      <header className="flex items-center gap-2.5 border-b border-hairline bg-surface-sidebar px-4 py-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent/10 text-accent-ink">
          <Search aria-hidden="true" className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-ink-faint">AI RESEARCH</p>
          <h2 id={titleId} className="truncate text-sm font-semibold tracking-tight text-ink" title={research.query || tab.title}>
            {research.query || "Kết quả AI research"}
          </h2>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
        {research.summary_markdown ? (
          <MarkdownContent content={research.summary_markdown} />
        ) : (
          <p className="text-sm text-ink-muted">Công cụ research không trả về phần tổng hợp bằng chữ; xem các nguồn bên dưới.</p>
        )}

        {sources.length > 0 && (
          <section className="mt-6">
            <h3 className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-faint">
              <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
              Nguồn tìm được ({sources.length})
            </h3>
            <ul className="space-y-2">
              {sources.map((source) => (
                <li key={source.url} className="group rounded-lg border border-hairline-subtle bg-surface-panel p-2.5 transition-colors duration-fast hover:border-hairline">
                  <SourceLink href={source.url} className="block text-sm font-medium text-ink transition-colors hover:text-accent-ink">
                    {source.source_id && <span className="mr-2 font-mono text-xs text-accent-ink">[{source.source_id}]</span>}
                    {source.title || source.url}
                  </SourceLink>
                  {source.snippet && <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-ink-muted">{source.snippet}</p>}
                  {source.publisher && <p className={cn("mt-1 text-[11px] text-ink-faint")}>{source.publisher}</p>}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </aside>
  );
}
