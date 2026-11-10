import type { ComponentProps } from "react";
import { evidenceUrl } from "@/lib/research";
import { useReportPreviewStore } from "@/stores/reportPreview";

export function SourceLink({ href, children, ...props }: ComponentProps<"a">) {
  const safe = evidenceUrl(href);
  const selected = useReportPreviewStore((state) => {
    const tab = state.tabs.find((item) => item.id === state.activeId);
    return tab?.selection.kind === "source" ? tab.selection.sourceUrl : null;
  });
  return <a {...props} href={safe ?? href} aria-current={safe && safe === selected ? "page" : undefined} target="_blank" rel="noopener noreferrer" onClick={(event) => {
    if (!safe || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    useReportPreviewStore.getState().openSource(safe, event.currentTarget.textContent || undefined);
  }}>{children}</a>;
}
