import { Search, ExternalLink } from "lucide-react";
import { useId } from "react";
import { MarkdownContent } from "./MessageBubble";
import { SourceLink } from "./SourceLink";
import { useReportPreviewStore, type ResearchSource } from "@/stores/reportPreview";

/**
 * The AI-search result, shown in the right-hand pane.
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
    <aside aria-labelledby={titleId} className="flex h-full min-h-0 w-full flex-col bg-background">
      <header className="flex items-center gap-2 border-b border-border bg-[#641C24] px-4 py-3 text-white">
        <Search aria-hidden="true" className="h-4 w-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold tracking-[0.15em] text-red-100">AI RESEARCH</p>
          <h2 id={titleId} className="truncate text-sm font-semibold" title={research.query || tab.title}>
            {research.query || "Kết quả AI research"}
          </h2>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        {research.summary_markdown ? (
          <MarkdownContent content={research.summary_markdown} />
        ) : (
          <p className="text-sm text-muted-foreground">Công cụ research không trả về phần tổng hợp bằng chữ; xem các nguồn bên dưới.</p>
        )}

        {sources.length > 0 && (
          <section className="mt-6">
            <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
              Nguồn thu thập ({sources.length})
            </h3>
            <ul className="space-y-2">
              {sources.map((source) => (
                <li key={source.url} className="rounded-lg border border-border/60 bg-card/40 p-2.5">
                  <SourceLink href={source.url} className="block text-sm font-medium text-foreground hover:underline">
                    {source.title || source.url}
                  </SourceLink>
                  {source.snippet && <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">{source.snippet}</p>}
                  {source.publisher && <p className="mt-1 text-[11px] text-muted-foreground/80">{source.publisher}</p>}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </aside>
  );
}
