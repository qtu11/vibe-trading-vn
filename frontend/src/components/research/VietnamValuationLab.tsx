import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { object, type ResearchObject, type ResearchValue } from "@/lib/research";
import comparablesExample from "@/data/research/vn-comparables.example.json?raw";
import dcfExample from "@/data/research/vn-dcf.example.json?raw";
import { parseResearchObject, researchButton as button, researchField as field, ResearchJsonEvidence, ResearchJsonInput } from "./ResearchJsonInput";
import { ResearchRevisionPanel } from "./ResearchRevisionPanel";

const show = (value: ResearchValue | undefined, missing: string) => value === null || value === undefined ? missing : typeof value === "object" ? JSON.stringify(value) : String(value);

function ValuationResult({ result, method }: { result: ResearchObject; method: "comparables" | "dcf" }) {
  const { t } = useTranslation(); const missing = t("marketResearch.unknown");
  const base = object(result.base_case), sensitivity = object(result.sensitivity), target = object(result.target);
  const grid = Array.isArray(sensitivity.cells) ? sensitivity.cells.flatMap((row) => Array.isArray(row) ? row.map(object) : []) : [];
  return <section className="space-y-3 rounded-lg border border-border bg-card p-4" aria-label={t("valuationLab.result")}>
    <h2 className="text-lg font-semibold">{t("valuationLab.result")}</h2>
    <p className="text-xs text-amber-700 dark:text-amber-300">{t("valuationLab.conditional")}</p>
    {method === "dcf" ? <>
      <div className="grid gap-3 sm:grid-cols-3">{["enterprise_value", "equity_value", "value_per_share"].map((key) => <div key={key} className="rounded border border-border p-3 text-xs"><p className="text-muted-foreground">{key.replace(/_/g, " ")} · {key === "value_per_share" ? "VND/share" : "VND"}</p><p className="mt-1 break-all font-mono">{show(base[key], missing)}</p></div>)}</div>
      <p className="text-xs text-muted-foreground">{t("valuationLab.gridExplanation")}</p>
      <div className="overflow-x-auto rounded border border-border"><table className="w-full text-xs"><caption className="p-3 text-start">{t("valuationLab.sensitivity")}</caption><thead className="border-y border-border bg-muted/40"><tr>{["WACC", "g", "VND/share", t("marketResearch.reason")].map((label) => <th scope="col" key={label} className="px-3 py-2 text-start">{label}</th>)}</tr></thead>
        <tbody>{grid.map((cell, index) => <tr className="border-b border-border/50 last:border-0" key={index}><td className="px-3 py-2">{show(cell.wacc, missing)}</td><td className="px-3 py-2">{show(cell.terminal_growth, missing)}</td><td className="px-3 py-2 font-mono">{show(cell.value_per_share_vnd, missing)}</td><td className="px-3 py-2">{show(cell.reason, "—")}</td></tr>)}</tbody></table></div>
    </> : <>
      <p className="text-sm">{show(target.symbol, missing)} · EPS {show(object(target.eps_vnd).value, missing)} VND · BVPS {show(object(target.bvps_vnd).value, missing)} VND</p>
      <ResearchJsonEvidence label={t("valuationLab.peerSummary")} data={{ distribution: result.distribution, target, paging: result.paging, aggregate_scope: result.aggregate_scope, sector_mismatches: result.sector_mismatches }} />
    </>}
    <ResearchJsonEvidence label={t("valuationLab.allEvidence")} data={result} />
  </section>;
}

export function VietnamValuationLab() {
  const { t } = useTranslation();
  const [method, setMethod] = useState<"comparables" | "dcf">("comparables"), [text, setText] = useState("");
  const [result, setResult] = useState<ResearchObject | null>(null), [input, setInput] = useState<ResearchObject | null>(null);
  const [offset, setOffset] = useState(0), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), [writing, setWriting] = useState(false);
  const generation = useRef(0), controller = useRef<AbortController | null>(null);
  useEffect(() => () => { generation.current++; controller.current?.abort(); }, []);
  function edit(value: string) { generation.current++; controller.current?.abort(); setText(value); setResult(null); setInput(null); setOffset(0); setBusy(false); setError(""); }
  async function evaluate(next = 0) {
    let payload: ResearchObject;
    try { payload = parseResearchObject(text) as ResearchObject; } catch { setError(t("valuationLab.invalidInput")); return; }
    const id = ++generation.current; controller.current?.abort(); const pending = new AbortController(); controller.current = pending;
    setBusy(true); setResult(null); setInput(null); setError("");
    try {
      const response = method === "dcf" ? await api.researchVietnamDCF(payload, pending.signal) : await api.researchVietnamComparables(payload, next, pending.signal);
      if (id !== generation.current) return;
      if (response.ok !== true) setError(typeof response.error === "string" ? response.error : t("valuationLab.failed"));
      else { setResult(response); setInput(payload); setOffset(next); }
    } catch (reason) { if (id === generation.current && !pending.signal.aborted) setError(reason instanceof Error ? reason.message : t("valuationLab.failed")); }
    finally { if (id === generation.current) setBusy(false); }
  }
  const paging = object(result?.paging), next = typeof paging.next_offset === "number" ? paging.next_offset : null;
  return <div className="space-y-5">
    <section className="space-y-4 rounded-lg border border-border bg-card p-4"><h2 className="text-lg font-semibold">{t("valuationLab.title")}</h2><p className="text-sm text-muted-foreground">{t("valuationLab.description")}</p>
      <label className="block max-w-sm space-y-1 text-xs"><span>{t("valuationLab.method")}</span><select className={field} value={method} disabled={writing} onChange={(event) => { edit(""); setMethod(event.target.value as typeof method); }}><option value="comparables">{t("valuationLab.comparables")}</option><option value="dcf">{t("valuationLab.dcf")}</option></select></label>
      <ResearchJsonInput text={text} onChange={edit} onError={setError} example={method === "dcf" ? dcfExample : comparablesExample} disabled={writing} />
      <div className="flex flex-wrap gap-3"><button type="button" className={button} disabled={!text.trim() || busy || writing} onClick={() => { void evaluate(); }}>{t("valuationLab.calculate")}</button>{busy && <button type="button" className={button} onClick={() => edit(text)}>{t("marketResearch.cancel")}</button>}</div>
    </section>
    {busy && <p role="status" className="text-sm text-muted-foreground">{t("marketResearch.loading")}</p>}
    {error && <p role="alert" className="rounded border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
    {result && <><ValuationResult result={result} method={method} />{next !== null && <button type="button" className={button} disabled={busy || writing} onClick={() => { void evaluate(next); }}>{t("valuationLab.nextPeers")}</button>}</>}
    <ResearchRevisionPanel kind={method === "dcf" ? "vietnam_dcf" : "vietnam_comparables"} request={input ? method === "dcf" ? input : { payload: input, offset } : null} onBusyChange={setWriting} />
  </div>;
}
