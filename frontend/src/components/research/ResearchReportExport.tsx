import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, downloadResearchMarkdown } from "@/lib/api";
import { evidenceUrl } from "@/lib/research";
import { researchButton as button } from "./ResearchJsonInput";

export function ResearchReportExport({ revisionId, disabled }: { revisionId: string; disabled: boolean }) {
  const { t } = useTranslation();
  const [markdown, setMarkdown] = useState<string | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), generation = useRef(0), controller = useRef<AbortController | null>(null);
  useEffect(() => { generation.current++; controller.current?.abort(); setMarkdown(null); setBusy(false); setError(""); }, [revisionId, disabled]);
  useEffect(() => () => { generation.current++; controller.current?.abort(); }, []);
  async function preview() {
    const id = ++generation.current; controller.current?.abort(); const current = new AbortController(); controller.current = current;
    setBusy(true); setError("");
    try { const result = await api.researchRevisionReport(revisionId, current.signal); if (id === generation.current) setMarkdown(result); }
    catch (reason) { if (id === generation.current && !current.signal.aborted) setError(reason instanceof Error ? reason.message : t("researchRevision.failed")); }
    finally { if (id === generation.current) setBusy(false); }
  }
  return <section className="space-y-3 border-t border-border pt-3" aria-label={t("researchRevision.reportTitle")}>
    <h3 className="text-sm font-semibold">{t("researchRevision.reportTitle")}</h3>
    <p className="text-xs text-muted-foreground">{t("researchRevision.reportExplanation")}</p>
    <div className="flex flex-wrap gap-3"><button type="button" className={button} disabled={disabled || busy} onClick={() => { void preview(); }}>{t("researchRevision.reportRead")}</button>
      <button type="button" className={button} disabled={disabled || markdown === null || busy} onClick={() => { if (markdown !== null) { try { downloadResearchMarkdown(revisionId, markdown); } catch { setError(t("researchRevision.reportDownloadFailed")); } } }}>{t("researchRevision.reportDownload")}</button></div>
    {busy && <p role="status" className="text-xs">{t("researchRevision.reading")}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {markdown !== null && <details className="rounded border border-border p-3" open><summary className="cursor-pointer text-sm">{t("researchRevision.reportPreview")}</summary>
      <div className="prose prose-sm mt-3 max-h-[36rem] max-w-none overflow-auto break-words dark:prose-invert">
        <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
          a: ({ href, children }) => { const safe = evidenceUrl(href); return safe ? <a href={safe} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>; },
          img: ({ alt }) => <span>{alt}</span>,
        }}>{markdown}</ReactMarkdown>
      </div>
    </details>}
  </section>;
}
