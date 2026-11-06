import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { ResearchObject } from "@/lib/research";
import type { ResearchKind, ResearchRevision, ResearchRevisionList } from "@/lib/researchArtifacts";
import { researchButton as button, researchField as field, ResearchJsonEvidence } from "./ResearchJsonInput";
import { ResearchAttemptHistory } from "./ResearchAttemptHistory";
import { ResearchReportExport } from "./ResearchReportExport";

export function ResearchRevisionPanel({ kind, request, onBusyChange }: {
  kind: ResearchKind; request: ResearchObject | null; onBusyChange?: (busy: boolean) => void;
}) {
  const { t } = useTranslation();
  const [list, setList] = useState<ResearchRevisionList | null>(null), [revision, setRevision] = useState<ResearchRevision | null>(null);
  const [diff, setDiff] = useState<ResearchObject | null>(null), [before, setBefore] = useState("");
  const [parent, setParent] = useState("");
  const [decision, setDecision] = useState<"acknowledged" | "changes_requested">("acknowledged");
  const [reviewer, setReviewer] = useState(""), [note, setNote] = useState("");
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [reading, setReading] = useState(false), [writing, setWriting] = useState(false);
  const [operationKey, setOperationKey] = useState("");
  const saveIntent = useRef<{ key: string; signature: string; request: ResearchObject; parent: string | undefined; kind: ResearchKind } | null>(null);
  const alive = useRef(true), pendingWrite = useRef(false), generation = useRef(0), controller = useRef<AbortController | null>(null);
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++; controller.current?.abort(); }; }, []);
  useEffect(() => { generation.current++; controller.current?.abort(); setList(null); setRevision(null); setDiff(null); setBefore(""); setParent(""); setError(""); setNotice(""); setReading(false); }, [kind]);
  useEffect(() => { saveIntent.current = null; setOperationKey(""); }, [kind]);

  async function read<T>(operation: (signal: AbortSignal) => Promise<T>, accept: (data: T) => void) {
    const id = ++generation.current; controller.current?.abort();
    const current = new AbortController(); controller.current = current; setReading(true); setError("");
    try { const result = await operation(current.signal); if (alive.current && id === generation.current) accept(result); }
    catch (reason) { if (alive.current && id === generation.current && !current.signal.aborted) setError(reason instanceof Error ? reason.message : t("researchRevision.failed")); }
    finally { if (alive.current && id === generation.current) setReading(false); }
  }
  function open(id: string) {
    setDiff(null); setRevision(null);
    void read((signal) => api.getResearchRevision(id, signal), (result) => { setRevision(result); setParent(result.revision_id); });
  }
  async function write(operation: () => Promise<void>) {
    if (pendingWrite.current) return;
    pendingWrite.current = true; generation.current++; controller.current?.abort(); setReading(false);
    setWriting(true); onBusyChange?.(true); setError(""); setNotice("");
    try { await operation(); }
    catch (reason) { if (alive.current) setError(`${reason instanceof Error ? reason.message : t("researchRevision.failed")} ${t("researchRevision.uncertain")}`); }
    finally { pendingWrite.current = false; if (alive.current) { setWriting(false); onBusyChange?.(false); } }
  }
  function save() {
    if (!request || pendingWrite.current) return;
    const signature = JSON.stringify({ kind, request, parent });
    if (!saveIntent.current || saveIntent.current.signature !== signature) {
      const entropy = crypto.getRandomValues(new Uint8Array(16));
      saveIntent.current = { key: "rk_" + Array.from(entropy, (value) => value.toString(16).padStart(2, "0")).join(""), signature,
        request: JSON.parse(JSON.stringify(request)) as ResearchObject, parent: parent || undefined, kind };
    }
    const intent = saveIntent.current; setOperationKey(intent.key);
    void write(async () => {
      const result = await api.saveResearchRevision(intent.kind, intent.request, intent.parent, intent.key);
      if (alive.current) { saveIntent.current = null; setRevision(result); setParent(result.revision_id); setDiff(null); setNotice(t("researchRevision.saved", { id: result.revision_id })); }
    });
  }
  function review() {
    if (!revision || !note.trim() || !reviewer.trim()) return;
    const id = revision.revision_id;
    void write(async () => {
      await api.reviewResearchRevision(id, decision, note, reviewer);
      if (!alive.current) return;
      setNotice(t("researchRevision.reviewSaved")); setNote("");
      // Refresh is a separate read. Its failure does not undo the review receipt.
      void read((signal) => api.getResearchRevision(id, signal), setRevision);
    });
  }
  return <section className="space-y-3 rounded-lg border border-border bg-card p-4" aria-label={t("researchRevision.title")}>
    <h2 className="font-semibold">{t("researchRevision.title")}</h2>
    <p className="text-xs text-muted-foreground">{t("researchRevision.explanation")}</p>
    <label className="block max-w-2xl space-y-1 text-xs"><span>{t("researchRevision.parent")}</span><select className={field} value={parent} disabled={writing} onChange={(event) => setParent(event.target.value)}>
      <option value="">{t("researchRevision.newLineage")}</option>
      {[...new Set([...(list?.items.map((item) => item.revision_id) ?? []), ...(parent ? [parent] : [])])].map((id) => <option key={id} value={id}>{id}</option>)}
    </select></label>
    <div className="flex flex-wrap gap-3"><button type="button" className={button} disabled={!request || writing} onClick={save}>{t("researchRevision.save")}</button>
      <button type="button" className={button} disabled={reading || writing} onClick={() => { void read((signal) => api.listResearchRevisions(kind, 0, signal), setList); }}>{t("researchRevision.history")}</button></div>
    {(reading || writing) && <p role="status" className="text-xs text-muted-foreground">{writing ? t("researchRevision.writing") : t("researchRevision.reading")}</p>}
    {error && <p role="alert" className="whitespace-pre-wrap rounded border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="break-all text-sm text-primary">{notice}</p>}
    {operationKey && <div className="space-y-2 text-xs"><p className="text-muted-foreground">{t("researchAttempt.keyExplanation")}</p><p className="break-all font-mono">{operationKey}</p>
      {saveIntent.current && <button type="button" className={button} disabled={writing} onClick={() => { saveIntent.current = null; setOperationKey(""); }}>{t("researchAttempt.newIntent")}</button>}
    </div>}
    <ResearchAttemptHistory kind={kind} revisionId={revision?.revision_id} operationKey={operationKey} disabled={writing} onOpen={open} />
    {list && <div className="space-y-2"><p className="text-xs text-muted-foreground">{t("researchRevision.total", { count: list.total })}</p>
      {list.items.map((item) => <button type="button" key={item.revision_id} disabled={writing} className={`${button} flex w-full flex-wrap justify-between gap-2 text-start text-xs`} onClick={() => open(item.revision_id)}><span className="break-all font-mono">{item.revision_id}</span><span>{item.created_at} · {item.review_state}</span></button>)}
      {list.next_offset !== null && <button type="button" className={button} disabled={reading || writing} onClick={() => { void read((signal) => api.listResearchRevisions(kind, list.next_offset!, signal), setList); }}>{t("researchRevision.next")}</button>}
    </div>}
    {revision && <div className="space-y-3 border-t border-border pt-3">
      <h3 className="break-all text-sm font-semibold">{revision.revision_id}</h3>
      <p className="text-xs">{revision.review_state} · {revision.verification_status} · {revision.content_scope}</p>
      <ResearchJsonEvidence label={t("researchRevision.evidence")} data={revision} />
      <ResearchReportExport key={revision.revision_id} revisionId={revision.revision_id} disabled={writing} />
      <div className="flex flex-wrap items-end gap-3"><label className="min-w-0 flex-1 space-y-1 text-xs"><span>{t("researchRevision.before")}</span><select className={field} value={before} disabled={writing} onChange={(event) => { generation.current++; controller.current?.abort(); setReading(false); setBefore(event.target.value); setDiff(null); }}><option value="">{t("researchRevision.choose")}</option>
        {(list?.items ?? []).filter((item) => item.revision_id !== revision.revision_id).map((item) => <option key={item.revision_id} value={item.revision_id}>{item.revision_id}</option>)}
        {revision.parent_revision_id && !list?.items.some((item) => item.revision_id === revision.parent_revision_id) && <option value={revision.parent_revision_id}>{revision.parent_revision_id}</option>}
      </select></label><button type="button" className={button} disabled={!before || writing || reading} onClick={() => { void read((signal) => api.diffResearchRevisions(before, revision.revision_id, signal), setDiff); }}>{t("researchRevision.compare")}</button></div>
      {diff && <ResearchJsonEvidence label={t("researchRevision.diff")} data={diff} />}
      <div className="space-y-3 border-t border-border pt-3"><p className="text-xs text-muted-foreground">{t("researchRevision.reviewExplanation")}</p>
        <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-xs"><span>{t("researchRevision.reviewer")}</span><input className={field} maxLength={120} disabled={writing} value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
          <label className="space-y-1 text-xs"><span>{t("researchRevision.decision")}</span><select className={field} disabled={writing} value={decision} onChange={(event) => setDecision(event.target.value as typeof decision)}><option value="acknowledged">{t("researchRevision.acknowledge")}</option><option value="changes_requested">{t("researchRevision.changes")}</option></select></label></div>
        <label className="block space-y-1 text-xs"><span>{t("researchRevision.note")}</span><textarea className={field} rows={3} maxLength={2000} disabled={writing} value={note} onChange={(event) => setNote(event.target.value)} /></label>
        <button type="button" className={button} disabled={writing || !note.trim() || !reviewer.trim()} onClick={review}>{t("researchRevision.review")}</button>
      </div>
    </div>}
  </section>;
}
