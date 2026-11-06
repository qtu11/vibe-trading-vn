import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { object, type ResearchObject, type ResearchValue } from "@/lib/research";
import example from "@/data/research/vn-reverse-dcf.example.json?raw";
import { parseResearchObject, researchButton as button, ResearchJsonEvidence, ResearchJsonInput } from "./ResearchJsonInput";
import { ResearchRevisionPanel } from "./ResearchRevisionPanel";

const show = (value: ResearchValue | undefined, missing: string) => value === null || value === undefined ? missing : String(value);

export function VietnamReverseDCFLab({ onBusyChange }: { onBusyChange?: (busy: boolean) => void }) {
  const { t } = useTranslation();
  const [text, setText] = useState(""), [error, setError] = useState("");
  const [result, setResult] = useState<ResearchObject | null>(null), [input, setInput] = useState<ResearchObject | null>(null);
  const [busy, setBusy] = useState(false), [writing, setWriting] = useState(false);
  const generation = useRef(0), controller = useRef<AbortController | null>(null);
  useEffect(() => () => { generation.current++; controller.current?.abort(); }, []);
  function edit(value: string) { generation.current++; controller.current?.abort(); setText(value); setResult(null); setInput(null); setBusy(false); setError(""); }
  async function evaluate() {
    let payload: ResearchObject;
    try { payload = parseResearchObject(text) as ResearchObject; } catch { setError(t("valuationLab.invalidInput")); return; }
    const id = ++generation.current; controller.current?.abort();
    const current = new AbortController(); controller.current = current;
    setBusy(true); setResult(null); setInput(null); setError("");
    try {
      const response = await api.researchVietnamReverseDCF(payload, current.signal);
      if (id !== generation.current) return;
      if (response.ok !== true) setError(typeof response.error === "string" ? response.error : t("valuationLab.failed"));
      else { setResult(response); setInput(payload); }
    } catch (reason) { if (id === generation.current && !current.signal.aborted) setError(reason instanceof Error ? reason.message : t("valuationLab.failed")); }
    finally { if (id === generation.current) setBusy(false); }
  }
  const solver = object(result?.solver), missing = t("marketResearch.unknown");
  return <div className="space-y-5">
    <section className="space-y-4 rounded-lg border border-border bg-card p-4">
      <h2 className="text-lg font-semibold">{t("reverseDCF.title")}</h2>
      <p className="text-sm text-muted-foreground">{t("reverseDCF.description")}</p>
      <ResearchJsonInput text={text} onChange={edit} onError={setError} example={example} disabled={writing} />
      <div className="flex flex-wrap gap-3"><button type="button" className={button} disabled={!text.trim() || busy || writing} onClick={() => { void evaluate(); }}>{t("reverseDCF.calculate")}</button>
        {busy && <button type="button" className={button} onClick={() => edit(text)}>{t("marketResearch.cancel")}</button>}</div>
    </section>
    {busy && <p role="status" className="text-sm text-muted-foreground">{t("marketResearch.loading")}</p>}
    {error && <p role="alert" className="rounded border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
    {result && <section className="space-y-3 rounded-lg border border-border bg-card p-4" aria-label={t("reverseDCF.result")}>
      <h2 className="font-semibold">{t("reverseDCF.result")} · {show(solver.status, missing)}</h2>
      <p className="text-xs text-amber-700 dark:text-amber-300">{t("reverseDCF.conditional")}</p>
      <div className="grid gap-3 sm:grid-cols-3">{([["growth", solver.implied_terminal_growth], ["repriced", solver.repriced_value_per_share_vnd], ["residual", solver.residual_vnd_per_share]] as const).map(([key, value]) => <div key={key} className="rounded border border-border p-3 text-xs"><p>{t(`reverseDCF.${key}`)}</p><p className="mt-1 break-all font-mono">{show(value, missing)}</p></div>)}</div>
      {solver.reason && <p className="text-xs text-muted-foreground">{show(solver.reason, missing)}</p>}
      <ResearchJsonEvidence label={t("reverseDCF.evidence")} data={result} />
    </section>}
    <ResearchRevisionPanel kind="vietnam_reverse_dcf" request={input} onBusyChange={(value) => { setWriting(value); onBusyChange?.(value); }} />
  </div>;
}
