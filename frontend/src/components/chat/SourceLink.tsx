import type { ComponentProps } from "react";
import { evidenceUrl } from "@/lib/research";
import { useReportPreviewStore } from "@/stores/reportPreview";

export function SourceLink({ href, children, ...props }: ComponentProps<"a">) {
  const safe = evidenceUrl(href);
  return <a {...props} href={safe ?? href} target="_blank" rel="noopener noreferrer" onClick={(event) => {
    if (!safe || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    useReportPreviewStore.getState().openSource(safe, event.currentTarget.textContent || undefined);
  }}>{children}</a>;
}
