import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { object, type ResearchObject, type ResearchValue } from "@/lib/research";
import example from "@/data/research/forex-regime.example.json?raw";
import { ResearchJsonEvidence, researchButton as button, researchField as field } from "@/components/research/ResearchJsonInput";

const MAX_BYTES = 1024 * 1024;
const cell = "px-3 py-2 text-start align-top";
const show = (value: ResearchValue | undefined, missing: string) => value === null || value === undefined ? missing : String(value);

/** Bounded JSON preview only; the server owns bar and calibration validation. */
export function parseRegimeRequest(text: string): ResearchObject {
  if (new TextEncoder().encode(text).byteLength > MAX_BYTES) throw new Error("too_large");
  const input: unknown = JSON.parse(text);
  if (input === null || typeof input !== "object" || Array.isArray(input)) throw new Error("request_object");
  const row = input as ResearchObject;
  if (!Array.isArray(row.bars) || row.bars.length < 32 || row.bars.length > 2000) throw new Error("request_bars");
  return row;
}

export function ForexRegimeLab() {
  const { t } = useTranslation();
  const [text, setText] = useState(""), [error, setError] = useState("");
  const [result, setResult] = useState<ResearchObject | null>(null), [input, setInput] = useState<ResearchObject | null>(null);
  const [busy, setBusy] = useState(false);
  const generation = useRef(0), fileGeneration = useRef(0), alive = useRef(true), controller = useRef<AbortController | null>(null);
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++; fileGeneration.current++; controller.current?.abort(); }; }, []);
  const validPreview = useMemo(() => { try { parseRegimeRequest(text); return true; } catch { return false; } }, [text]);
  function edit(value: string) {
    generation.current++; fileGeneration.current++; controller.current?.abort();
    setText(value); setResult(null); setInput(null); setBusy(false); setError("");
  }
  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; event.target.value = "";
    if (!file) return;
    const id = ++fileGeneration.current;
    if (file.size > MAX_BYTES) { setError(t("forexRegime.invalid")); return; }
    try {
      const value = await file.text(); parseRegimeRequest(value);
      if (alive.current && id === fileGeneration.current) edit(value);
    } catch { if (alive.current && id === fileGeneration.current) setError(t("forexRegime.invalid")); }
  }
  async function replay(offset?: number) {
    let payload: ResearchObject;
    try { payload = offset !== undefined && input ? { ...input, offset } : parseRegimeRequest(text); }
    catch { setError(t("forexRegime.invalid")); return; }
    const id = ++generation.current; controller.current?.abort();
    const current = new AbortController(); controller.current = current;
    setBusy(true); setResult(null); setInput(null); setError("");
    try {
      const response = await api.forexRegime(payload, current.signal);
      if (!alive.current || id !== generation.current) return;
      setResult(response); setInput(payload);
    } catch (reason) { if (alive.current && id === generation.current && !current.signal.aborted) setError(reason instanceof Error ? reason.message : t("forexRegime.failed")); }
    finally { if (alive.current && id === generation.current) setBusy(false); }
  }
  function download() {
    if (!result || !input) return;
    const content = { schema_version: 1, export_scope: "request_and_one_returned_timeline_page", request: input, result };
    const url = URL.createObjectURL(new Blob([JSON.stringify(content, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = "forex-regime-replay.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const missing = t("forexRegime.unknown"), calibration = object(result?.calibration), summary = object(result?.summary), latest = object(result?.latest), paging = object(result?.paging);
  const rows = Array.isArray(result?.timeline) ? result.timeline.map(object) : [];
  const offset = typeof paging.offset === "number" ? paging.offset : 0, limit = typeof paging.limit === "number" ? paging.limit : 50;
  return <section className="space-y-5" aria-label={t("forexRegime.title")}>
    <div className="space-y-3 rounded-lg border border-border bg-card p-4"><h2 className="text-lg font-semibold">{t("forexRegime.title")}</h2>
      <p className="max-w-4xl text-sm text-muted-foreground">{t("forexRegime.description")}</p>
      <div className="flex flex-wrap items-center gap-3"><label className={`${button} cursor-pointer`}>{t("forexRegime.import")}<input type="file" className="sr-only" aria-label={t("forexRegime.import")} accept=".json,application/json" onChange={(event) => { void upload(event); }} /></label>
        <button type="button" className={button} onClick={() => edit(example)}>{t("forexRegime.example")}</button></div>
      <p className="text-xs text-amber-700 dark:text-amber-300">{t("forexRegime.synthetic")}</p>
      <label className="block space-y-1 text-xs font-medium"><span>{t("forexRegime.input")}</span><textarea className={`${field} min-h-56 font-mono text-xs`} maxLength={MAX_BYTES} value={text} onChange={(event) => edit(event.target.value)} spellCheck={false} dir="ltr" /></label>
      <div className="flex flex-wrap gap-3"><button type="button" className={`${button} bg-primary/10 text-primary`} disabled={!validPreview || busy} onClick={() => { void replay(); }}>{t("forexRegime.calculate")}</button>
        {busy && <button type="button" className={button} onClick={() => { generation.current++; controller.current?.abort(); setBusy(false); }}>{t("forexRegime.cancel")}</button>}</div>
    </div>
    {busy && <p role="status" className="text-sm text-muted-foreground">{t("forexRegime.loading")}</p>}
    {error && <p role="alert" className="rounded border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
    {result && <div className="space-y-4 rounded-lg border border-border bg-card p-4">
      {result.status !== "ok" && <p className="text-sm">{t("forexRegime.unavailable")} {show(result.code, missing)}</p>}
      <section className="space-y-2" aria-label={t("forexRegime.calibration")}><h3 className="font-semibold">{t("forexRegime.calibration")}</h3>
        <dl className="grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-3">{([
          ["trainEnd", "train_end_index"], ["trainingAvailable", "last_training_available_at"], ["firstDecision", "first_decision_available_at"],
          ["entry", "entry_threshold"], ["exit", "exit_threshold"], ["features", "feature_count"],
        ] as const).map(([label, key]) => <div key={key} className="rounded border border-border p-3"><dt className="text-muted-foreground">{t(`forexRegime.${label}`)}</dt><dd className="mt-1 break-all font-mono">{show(calibration[key], missing)}</dd></div>)}</dl>
      </section>
      <section aria-label={t("forexRegime.latest")}><h3 className="font-semibold">{t("forexRegime.latest")}</h3><p className="mt-2 break-words text-sm">{show(latest.regime, missing)} · {show(latest.available_at, missing)} · {show(latest.reason, missing)}</p></section>
      <section aria-label={t("forexRegime.summary")}><h3 className="font-semibold">{t("forexRegime.summary")}</h3><dl className="mt-2 grid gap-2 text-xs sm:grid-cols-3">{Object.entries(summary).map(([key, amount]) => <div key={key} className="rounded border border-border p-2"><dt>{key.replace(/_/g, " ")}</dt><dd className="mt-1 font-mono">{show(amount, missing)}</dd></div>)}</dl></section>
      <div className="overflow-x-auto rounded border border-border"><table className="w-full text-xs"><caption className="p-3 text-start font-medium">{t("forexRegime.timeline")}</caption><thead className="border-y bg-muted/40"><tr>
        {(["index", "available", "phase", "slope", "state", "reason", "dwell"] as const).map((key) => <th scope="col" key={key} className={cell}>{t(`forexRegime.${key}`)}</th>)}
      </tr></thead><tbody>{rows.map((row) => <tr key={String(row.index)} className="border-b last:border-0"><th scope="row" className={cell}>{show(row.index, missing)}</th>
        <td className={cell}>{show(row.available_at, missing)}</td><td className={cell}>{show(row.phase, missing)}</td><td className={cell}>{show(row.normalized_slope, missing)}</td><td className={cell}>{show(row.regime, missing)}</td><td className={cell}>{show(row.reason, missing)}</td><td className={cell}>{show(row.dwell_remaining, missing)}</td></tr>)}</tbody></table></div>
      <div className="flex flex-wrap items-center gap-3"><p className="text-xs">{t("forexRegime.page", { start: rows.length ? offset + 1 : 0, end: offset + rows.length, total: paging.total ?? 0 })}</p>
        <button type="button" className={button} disabled={busy || offset === 0} onClick={() => { void replay(Math.max(0, offset - limit)); }}>{t("forexRegime.previous")}</button>
        <button type="button" className={button} disabled={busy || typeof paging.next_offset !== "number"} onClick={() => { if (typeof paging.next_offset === "number") void replay(paging.next_offset); }}>{t("forexRegime.next")}</button>
        <button type="button" className={button} onClick={download}>{t("forexRegime.export")}</button></div>
      <ResearchJsonEvidence label={t("forexRegime.evidence")} data={result} />
    </div>}
    <p className="text-xs text-muted-foreground">{t("forexRegime.limits")}</p>
  </section>;
}
