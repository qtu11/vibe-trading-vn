import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { ResearchAttemptList, ResearchKind } from "@/lib/researchArtifacts";
import { researchButton as button, researchField as field, ResearchJsonEvidence } from "./ResearchJsonInput";

export function ResearchAttemptHistory({ kind, revisionId, operationKey, disabled, onOpen }: {
  kind: ResearchKind; revisionId?: string; operationKey: string; disabled: boolean; onOpen: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [scope, setScope] = useState<"all" | "revision" | "key">("all");
  const [data, setData] = useState<ResearchAttemptList | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0), controller = useRef<AbortController | null>(null);
  useEffect(() => { generation.current++; controller.current?.abort(); setData(null); setBusy(false); setError(""); }, [kind, revisionId, operationKey, disabled]);
  useEffect(() => () => { generation.current++; controller.current?.abort(); }, []);
  async function load(offset = 0) {
    const id = ++generation.current; controller.current?.abort();
    const current = new AbortController(); controller.current = current; setBusy(true); setError("");
    try {
      const result = await api.listResearchAttempts(kind, scope === "revision" ? revisionId : undefined, scope === "key" ? operationKey : undefined, offset, current.signal);
      if (id === generation.current) setData(result);
    } catch (reason) { if (id === generation.current && !current.signal.aborted) setError(reason instanceof Error ? reason.message : t("researchRevision.failed")); }
    finally { if (id === generation.current) setBusy(false); }
  }
  const canRead = scope === "all" || (scope === "revision" ? Boolean(revisionId) : Boolean(operationKey));
  return <section className="space-y-3 border-t border-border pt-3" aria-label={t("researchAttempt.title")}>
    <h3 className="text-sm font-semibold">{t("researchAttempt.title")}</h3>
    <p className="text-xs text-muted-foreground">{t("researchAttempt.explanation")}</p>
    <label className="block max-w-xl space-y-1 text-xs"><span>{t("researchAttempt.scope")}</span><select className={field} value={scope} disabled={disabled} onChange={(event) => { generation.current++; controller.current?.abort(); setScope(event.target.value as typeof scope); setData(null); setBusy(false); setError(""); }}>
      <option value="all">{t("researchAttempt.all")}</option><option value="revision" disabled={!revisionId}>{t("researchAttempt.revision")}</option><option value="key" disabled={!operationKey}>{t("researchAttempt.key")}</option>
    </select></label>
    {scope !== "all" && <p className="break-all font-mono text-xs">{scope === "revision" ? revisionId : operationKey}</p>}
    <button type="button" className={button} disabled={disabled || busy || !canRead} onClick={() => { void load(); }}>{t("researchAttempt.read")}</button>
    {busy && <p role="status" className="text-xs">{t("researchRevision.reading")}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {data && <div className="space-y-3">
      {data.refresh_state && <p className="rounded border border-amber-500/30 p-3 text-xs">{t(`researchAttempt.${data.refresh_state.state}`)}</p>}
      <p className="text-xs">{t("researchAttempt.total", { count: data.total })}</p>
      {data.items.map((item) => <div key={item.attempt_id} className="space-y-1 rounded border border-border p-3 text-xs">
        <p className="break-all font-mono">{item.attempt_id}</p><p>{t(`researchAttempt.${item.status}`)} · {item.created_at}</p>
        {item.error && <p className="break-words text-destructive">{item.error.code} · {item.error.message}</p>}
        {item.revision_id && <button type="button" className={`${button} break-all`} disabled={disabled} onClick={() => onOpen(item.revision_id!)}>{item.revision_id}</button>}
      </div>)}
      {data.next_offset !== null && <button type="button" className={button} disabled={busy || disabled} onClick={() => { void load(data.next_offset!); }}>{t("researchAttempt.next")}</button>}
      <ResearchJsonEvidence label={t("researchAttempt.evidence")} data={data} />
    </div>}
  </section>;
}
