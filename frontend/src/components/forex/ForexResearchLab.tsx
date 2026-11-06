import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { MAX_RESEARCH_BYTES, forexLabMethod, parseForexLab, syntheticCostStressRequest, syntheticForexRequest, syntheticTradePathsRequest, type ForexCostStressRequest, type ForexExperimentDetail, type ForexExperimentList, type ForexExperimentRun, type ForexLabMethod, type ForexLabRequest, type ForexResearchRequest, type ForexResearchResult, type ForexTradePathsRequest } from "@/lib/forexResearch";
import { object, type ResearchValue } from "@/lib/research";

const button = "rounded-md border border-border px-3 py-2 text-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";
const control = "w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";
const cell = "px-3 py-2 text-start align-top";
const value = (input: ResearchValue | undefined, missing: string) => input === null || input === undefined ? missing : typeof input === "object" ? JSON.stringify(input) : String(input);

function JsonEvidence({ label, data }: { label: string; data: unknown }) {
  return <details className="rounded-md border border-border p-3"><summary className="cursor-pointer text-sm font-medium">{label}</summary>
    <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all rounded bg-muted/30 p-3 text-xs" dir="ltr">{JSON.stringify(data, null, 2)}</pre>
  </details>;
}

function TradePathChart({ display }: { display: ResearchValue | undefined }) {
  const { t } = useTranslation();
  const data = object(display), bands = object(data.bands);
  const numbers = (values: ResearchValue | undefined): number[] => Array.isArray(values) && values.every((item) => typeof item === "number" && Number.isFinite(item)) ? (values as number[]).slice(0, 100) : [];
  const steps = numbers(data.steps), actual = numbers(data.actual), lower = numbers(bands.p05), upper = numbers(bands.p95), median = numbers(bands.p50);
  if (steps.length < 2 || [actual, lower, upper, median].some((items) => items.length !== steps.length)) return null;
  const samples = Array.isArray(data.samples) ? data.samples.slice(0, 20).map(numbers).filter((items) => items.length === steps.length) : [];
  const all = [...actual, ...lower, ...upper, ...samples.flat()];
  const low = Math.min(...all), high = Math.max(...all), span = high - low || 1;
  const x = (index: number) => 12 + (steps[index] - steps[0]) / (steps[steps.length - 1] - steps[0] || 1) * 576;
  const y = (amount: number) => 160 - (amount - low) / span * 140;
  const points = (values: number[]) => values.map((amount, index) => `${x(index)},${y(amount)}`).join(" ");
  const area = `${points(lower)} ${upper.map((amount, index) => `${x(index)},${y(amount)}`).reverse().join(" ")}`;
  return <figure className="space-y-2 rounded border border-border p-3"><svg role="img" aria-label={t("forexLab.pathsChart")} viewBox="0 0 600 180" className="w-full">
    <polygon points={area} fill="currentColor" className="text-primary" opacity="0.12" />
    {samples.map((path, index) => <polyline key={index} points={points(path)} fill="none" stroke="currentColor" className="text-muted-foreground" opacity="0.2" strokeWidth="0.7" />)}
    <polyline points={points(median)} fill="none" stroke="currentColor" className="text-amber-600 dark:text-amber-300" strokeWidth="1.5" />
    <polyline points={points(actual)} fill="none" stroke="currentColor" className="text-primary" strokeWidth="2.5" />
    <text x="12" y="176" className="fill-current text-[10px]">{steps[0]}</text><text x="588" y="176" textAnchor="end" className="fill-current text-[10px]">{steps[steps.length - 1]}</text>
  </svg><figcaption className="text-xs text-muted-foreground">{t("forexLab.pathsSample")} · p05–p95 · {t("forexLab.actualPath")}</figcaption></figure>;
}

function Evaluation({ result }: { result: ForexResearchResult }) {
  const { t } = useTranslation();
  const missing = t("forexLab.unknown");
  const folds = Array.isArray(result.folds) ? result.folds.map(object) : [];
  const aggregate = object(result.out_of_sample_metrics);
  if (result.experiment_kind === "frozen_oos_moving_block_bootstrap") {
    const summary = object(result.simulation_summary), terminal = object(summary.terminal_net_return_quantiles), drawdown = object(summary.max_drawdown_quantiles);
    const actual = object(result.actual_path), config = object(result.config);
    return <section className="space-y-3" aria-label={t("forexLab.pathsResult")}><h3 className="font-semibold">{t("forexLab.pathsResult")} · {result.status}</h3>
      <p className="text-xs text-muted-foreground">{t("forexLab.pathsExplanation")}</p><p className="break-all font-mono text-xs">{value(result.frozen_oos_tape_hash, missing)}</p>
      <p className="text-xs">{t("forexLab.seed")}: {value(config.seed, missing)} · {t("forexLab.simulations")}: {value(config.simulations, missing)} · {t("forexLab.blockLength")}: {value(config.block_length, missing)}</p>
      <div aria-label={t("forexLab.actualPath")} className="rounded border border-border p-3 text-xs"><p className="font-medium">{t("forexLab.actualPath")}</p>
        <p>{t("forexLab.trades")}: {value(actual.trade_count, missing)} · {t("forexLab.netReturn")}: {value(actual.net_return, missing)} · {t("forexLab.drawdown")}: {value(actual.max_drawdown, missing)}</p>
      </div>
      {result.status !== "ok" && <p className="text-xs text-muted-foreground">{t("forexLab.pathsUnavailable")} {value(result.code, missing)}</p>}
      <div className="overflow-x-auto rounded border border-border"><table className="w-full text-xs"><thead className="border-b bg-muted/40"><tr>
        {(["quantile", "terminalReturn", "drawdown"] as const).map((key) => <th scope="col" className={cell} key={key}>{t(`forexLab.${key}`)}</th>)}
      </tr></thead><tbody>{["p05", "p25", "p50", "p75", "p95"].map((key) => <tr key={key} className="border-b last:border-0"><th scope="row" className={cell}>{key}</th><td className={cell}>{value(terminal[key], missing)}</td><td className={cell}>{value(drawdown[key], missing)}</td></tr>)}</tbody></table></div>
      <TradePathChart display={result.display_paths} />
      <JsonEvidence label={t("forexLab.simulationSummary")} data={result.simulation_summary} />
      <JsonEvidence label={t("forexLab.allTrials")} data={result} />
    </section>;
  }
  if (result.experiment_kind === "frozen_oos_cost_stress") {
    const scenarios = Array.isArray(result.scenarios) ? result.scenarios.map(object) : [];
    return <section className="space-y-3" aria-label={t("forexLab.stressResult")}><h3 className="font-semibold">{t("forexLab.stressResult")} · {result.status}</h3>
      <p className="text-xs text-muted-foreground">{t("forexLab.frozenExplanation")}</p><p className="break-all font-mono text-xs">{value(result.frozen_oos_tape_hash, missing)}</p>
      <div className="overflow-x-auto rounded border border-border"><table className="w-full text-xs"><thead className="border-b bg-muted/40"><tr>{(["spreadMultiplier", "allInCost", "netReturn", "expectancy", "breakEven", "status"] as const).map((key) => <th scope="col" key={key} className={cell}>{t(`forexLab.${key}`)}</th>)}</tr></thead>
        <tbody>{scenarios.map((scenario, index) => { const metrics = object(scenario.out_of_sample_metrics); return <tr key={index} className="border-b last:border-0"><th scope="row" className={cell}>{value(scenario.spread_multiplier, missing)}</th><td className={cell}>{value(scenario.round_trip_cost_bps, missing)}</td><td className={cell}>{value(metrics.net_return, missing)}</td><td className={cell}>{value(metrics.net_expectancy_bps, missing)}</td><td className={cell}>{value(metrics.arithmetic_break_even_spread_bps, missing)}</td><td className={cell}>{value(scenario.status, missing)}</td></tr>; })}</tbody></table></div>
      <JsonEvidence label={t("forexLab.allTrials")} data={result} />
    </section>;
  }
  return <section className="space-y-3" aria-label={t("forexLab.evaluation")}>
    <h3 className="text-base font-semibold">{t("forexLab.evaluation")} · {result.status}</h3>
    <p className="text-xs text-muted-foreground">{value(result.strategy_variant, missing)}</p>
    {result.out_of_sample_metrics === null && <p className="text-sm text-muted-foreground">{t("forexLab.incomplete")}</p>}
    <div className="grid gap-3 sm:grid-cols-3">{Object.entries(aggregate).map(([key, amount]) => <div key={key} className="rounded border border-border p-3 text-xs"><p className="text-muted-foreground">{key.replace(/_/g, " ")}</p><p className="mt-1 break-words font-mono">{value(amount, missing)}</p></div>)}</div>
    <div className="overflow-x-auto rounded border border-border"><table className="w-full text-xs">
      <caption className="p-3 text-start">{t("forexLab.folds")}</caption><thead className="border-y border-border bg-muted/40"><tr>
        {(["fold", "trainEnd", "testWindow", "selected", "trades", "netReturn", "status"] as const).map((key) => <th scope="col" key={key} className={cell}>{t(`forexLab.${key}`)}</th>)}
      </tr></thead><tbody>{folds.map((fold) => {
        const train = object(fold.training), test = object(fold.out_of_sample), metrics = object(fold.out_of_sample_metrics);
        return <tr key={String(fold.fold)} className="border-b border-border/50 last:border-0">
          <th scope="row" className={cell}>{value(fold.fold, missing)}</th>
          <td className={cell}>{value(train.outcome_available_at, missing)}</td><td className={cell}>{value(test.signal_start, missing)} → {value(test.outcome_available_at, missing)}</td>
          <td className={cell}>{value(fold.selected, missing)}</td><td className={cell}>{value(metrics.trade_count, missing)}</td>
          <td className={cell}>{value(metrics.net_return, missing)}</td><td className={cell}>{value(fold.status, missing)}{fold.code ? ` · ${fold.code}` : ""}</td>
        </tr>;
      })}</tbody>
    </table></div>
    <JsonEvidence label={t("forexLab.allTrials")} data={result} />
  </section>;
}

export function ForexResearchLab({ onBusyChange }: { onBusyChange?: (busy: boolean) => void } = {}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState("");
  const [method, setMethod] = useState<ForexLabMethod>("walk_forward");
  const [result, setResult] = useState<ForexResearchResult | null>(null);
  const [evaluated, setEvaluated] = useState<ForexLabRequest | null>(null);
  const [busy, setBusy] = useState(false), [saving, setSaving] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [history, setHistory] = useState<ForexExperimentList | null>(null);
  const [experiment, setExperiment] = useState<ForexExperimentDetail | null>(null);
  const [run, setRun] = useState<ForexExperimentRun | null>(null);
  const [destination, setDestination] = useState("");
  const [historyBusy, setHistoryBusy] = useState(false), [detailBusy, setDetailBusy] = useState(false);
  const read = useRef<AbortController | null>(null), historyRead = useRef<AbortController | null>(null), detailRead = useRef<AbortController | null>(null);
  const generation = useRef(0), historyGeneration = useRef(0), detailGeneration = useRef(0), uploadGeneration = useRef(0), alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++; historyGeneration.current++; detailGeneration.current++; uploadGeneration.current++; read.current?.abort(); historyRead.current?.abort(); detailRead.current?.abort(); }; }, []);
  const preview = useMemo(() => { try { const request = parseForexLab(draft, method); return method === "walk_forward" ? request as ForexResearchRequest : (request as ForexTradePathsRequest).research; } catch { return null; } }, [draft, method]);
  function edit(text: string) {
    generation.current++; uploadGeneration.current++; read.current?.abort();
    setDraft(text); setBusy(false); setResult(null); setEvaluated(null); setError(""); setNotice("");
  }
  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const id = ++uploadGeneration.current;
    if (file.size > MAX_RESEARCH_BYTES) { setError(t("forexLab.tooLarge")); return; }
    try {
      const text = await file.text();
      if (alive.current && id === uploadGeneration.current) { parseForexLab(text, method); edit(text); }
    } catch { if (alive.current && id === uploadGeneration.current) setError(t("forexLab.invalidJson")); }
  }
  async function calculate() {
    let payload: ForexLabRequest;
    try { payload = parseForexLab(draft, method); } catch { setError(t("forexLab.invalidJson")); return; }
    const id = ++generation.current;
    read.current?.abort(); const controller = new AbortController(); read.current = controller;
    setBusy(true); setResult(null); setEvaluated(null); setError(""); setNotice("");
    try {
      const response = method === "trade_paths" ? await api.forexTradePaths(payload as ForexTradePathsRequest, controller.signal) : method === "cost_stress" ? await api.forexCostStress(payload as ForexCostStressRequest, controller.signal) : await api.forexWalkForward(payload as ForexResearchRequest, controller.signal);
      if (!alive.current || id !== generation.current) return;
      setResult(response); setEvaluated(payload);
    } catch (reason) { if (alive.current && id === generation.current && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : t("forexLab.failed")); }
    finally { if (alive.current && id === generation.current) setBusy(false); }
  }
  async function loadHistory(offset = 0) {
    const id = ++historyGeneration.current; historyRead.current?.abort();
    const controller = new AbortController(); historyRead.current = controller; setHistoryBusy(true); setError("");
    try { const response = await api.listForexExperiments(offset, controller.signal); if (alive.current && id === historyGeneration.current) setHistory(response); }
    catch (reason) { if (alive.current && id === historyGeneration.current && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : t("forexLab.failed")); }
    finally { if (alive.current && id === historyGeneration.current) setHistoryBusy(false); }
  }
  async function loadExperiment(id: string, offset = 0) {
    const request = ++detailGeneration.current; detailRead.current?.abort();
    const controller = new AbortController(); detailRead.current = controller;
    setDetailBusy(true); setRun(null); setExperiment(null); setError("");
    try { const response = await api.getForexExperiment(id, offset, controller.signal); if (alive.current && request === detailGeneration.current) { setExperiment(response); setDestination(response.id); } }
    catch (reason) { if (alive.current && request === detailGeneration.current && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : t("forexLab.failed")); }
    finally { if (alive.current && request === detailGeneration.current) setDetailBusy(false); }
  }
  async function loadRun(experimentId: string, runId: string) {
    const id = ++detailGeneration.current; detailRead.current?.abort();
    const controller = new AbortController(); detailRead.current = controller; setDetailBusy(true); setRun(null); setError("");
    try { const response = await api.getForexExperimentRun(experimentId, runId, controller.signal); if (alive.current && id === detailGeneration.current) setRun(response); }
    catch (reason) { if (alive.current && id === detailGeneration.current && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : t("forexLab.failed")); }
    finally { if (alive.current && id === detailGeneration.current) setDetailBusy(false); }
  }
  async function save() {
    if (!evaluated || saving) return;
    // A file read begun before this write must not replace its frozen inputs.
    uploadGeneration.current++;
    detailGeneration.current++; detailRead.current?.abort(); setDetailBusy(false);
    onBusyChange?.(true);
    setSaving(true); setError(""); setNotice("");
    try {
      // One deliberate write. Never abort/retry it on an ambiguous timeout.
      const saved = method === "trade_paths" ? await api.saveForexTradePathsExperiment(evaluated as ForexTradePathsRequest, destination || undefined) : method === "cost_stress" ? await api.saveForexCostStressExperiment(evaluated as ForexCostStressRequest, destination || undefined) : await api.saveForexExperiment(evaluated as ForexResearchRequest, destination || undefined);
      if (!alive.current) return;
      setRun(saved); setDestination(saved.experiment_id); setNotice(t("forexLab.saved", { id: saved.id, status: saved.status }));
      void loadHistory();
    } catch (reason) { if (alive.current) setError(`${reason instanceof Error ? reason.message : t("forexLab.failed")} ${t("forexLab.checkHistory")}`); }
    finally { if (alive.current) { setSaving(false); onBusyChange?.(false); } }
  }

  return <section className="space-y-5" aria-label={t("forexLab.title")}>
    <div className="space-y-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-lg font-semibold">{t("forexLab.title")}</h2>
      <p className="max-w-4xl text-sm text-muted-foreground">{t("forexLab.description")}</p>
      <label className="block max-w-sm space-y-1 text-xs"><span>{t("forexLab.method")}</span><select className={control} value={method} disabled={saving} onChange={(event) => { edit(""); setMethod(event.target.value as typeof method); }}><option value="walk_forward">{t("forexLab.walkForward")}</option><option value="cost_stress">{t("forexLab.costStress")}</option><option value="trade_paths">{t("forexLab.tradePaths")}</option></select></label>
      <div className="flex flex-wrap items-center gap-3">
        <label className={`${button} ${saving ? "opacity-50" : "cursor-pointer"}`}>{t("forexLab.import")}<input aria-label={t("forexLab.import")} type="file" accept=".json,application/json" className="sr-only" disabled={saving} onChange={(event) => { void upload(event); }} /></label>
        <button type="button" className={button} disabled={saving} onClick={() => edit(JSON.stringify(method === "trade_paths" ? syntheticTradePathsRequest() : method === "cost_stress" ? syntheticCostStressRequest() : syntheticForexRequest(), null, 2))}>{t("forexLab.example")}</button>
      </div>
      <p className="text-xs text-amber-700 dark:text-amber-300">{t("forexLab.synthetic")}</p>
      <label className="block space-y-1 text-xs font-medium"><span>{t("forexLab.input")}</span><textarea className={`${control} min-h-48 font-mono text-xs`} value={draft} maxLength={MAX_RESEARCH_BYTES} disabled={saving} onChange={(event) => edit(event.target.value)} spellCheck={false} dir="ltr" /></label>
      {preview && <p className="break-words text-xs text-muted-foreground">{t("forexLab.preview", { symbol: preview.symbol, bars: preview.bars.length, candidates: preview.candidates.length, revision: preview.dataset_revision, cost: preview.round_trip_cost_bps })}</p>}
      <div className="flex flex-wrap gap-3"><button type="button" className={`${button} bg-primary/10 text-primary`} disabled={!preview || busy || saving} onClick={() => { void calculate(); }}>{busy ? t("forexLab.calculating") : t("forexLab.calculate")}</button>
        {busy && <button type="button" className={button} onClick={() => { generation.current++; read.current?.abort(); setBusy(false); }}>{t("forexLab.cancel")}</button>}
      </div>
    </div>
    {(busy || saving || historyBusy || detailBusy) && <p role="status" className="text-sm text-muted-foreground">{saving ? t("forexLab.saving") : t("forexLab.loading")}</p>}
    {error && <p role="alert" className="whitespace-pre-wrap rounded border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded border border-primary/30 p-3 text-sm">{notice}</p>}
    {result && <div className="space-y-4 rounded-lg border border-border bg-card p-4"><Evaluation result={result} />
      <div className="space-y-2 border-t border-border pt-3"><p className="text-xs text-muted-foreground">{t("forexLab.saveExplanation")}</p>
        <label className="block max-w-xl space-y-1 text-xs"><span>{t("forexLab.destination")}</span><select className={control} value={destination} disabled={saving} onChange={(event) => setDestination(event.target.value)}><option value="">{t("forexLab.newExperiment")}</option>
          {[...new Set([...(history?.experiments.map((item) => item.id) ?? []), ...(destination ? [destination] : [])])].map((id) => <option key={id} value={id}>{id}</option>)}
        </select></label><button type="button" className={button} disabled={saving} onClick={() => { void save(); }}>{t("forexLab.save")}</button>
      </div>
    </div>}
    <section className="space-y-3 rounded-lg border border-border bg-card p-4" aria-label={t("forexLab.history")}>
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">{t("forexLab.history")}</h2><button type="button" className={button} disabled={historyBusy || saving} onClick={() => { void loadHistory(); }}>{t("forexLab.refresh")}</button></div>
      <p className="text-xs text-muted-foreground">{t("forexLab.historyDescription")}</p>
      {history && <><p className="text-xs text-muted-foreground">{t("forexLab.total", { total: history.total })}</p>
        <div className="space-y-2">{history.experiments.map((item) => <button type="button" className={`${button} flex w-full flex-wrap justify-between gap-2 text-start`} key={item.id} disabled={saving || detailBusy} onClick={() => { void loadExperiment(item.id); }}><span className="break-all font-mono text-xs">{item.id}</span><span className="text-xs">{item.created_at} · {t("forexLab.attempts", { count: item.attempt_count })}</span></button>)}</div>
        <div className="flex gap-2"><button type="button" className={button} disabled={historyBusy || history.offset === 0 || saving} onClick={() => { void loadHistory(Math.max(0, history.offset - history.limit)); }}>{t("forexLab.previous")}</button><button type="button" className={button} disabled={historyBusy || history.offset + history.experiments.length >= history.total || saving} onClick={() => { void loadHistory(history.offset + history.limit); }}>{t("forexLab.next")}</button></div>
      </>}
      {experiment && <div className="space-y-3 border-t border-border pt-3"><h3 className="break-all text-sm font-medium">{experiment.id}</h3>
        {experiment.runs.map((item) => <button key={item.id} type="button" className={`${button} flex w-full flex-wrap justify-between gap-2 text-start text-xs`} disabled={saving || detailBusy} onClick={() => { void loadRun(experiment.id, item.id); }}><span className="break-all font-mono">#{item.attempt} · {item.id}</span><span>{item.status} · {item.created_at}</span></button>)}
        <div className="flex gap-2"><button type="button" className={button} disabled={detailBusy || experiment.offset === 0 || saving} onClick={() => { void loadExperiment(experiment.id, Math.max(0, experiment.offset - experiment.limit)); }}>{t("forexLab.previousRuns")}</button><button type="button" className={button} disabled={detailBusy || experiment.offset + experiment.runs.length >= experiment.attempt_count || saving} onClick={() => { void loadExperiment(experiment.id, experiment.offset + experiment.limit); }}>{t("forexLab.nextRuns")}</button></div>
      </div>}
      {run && <div className="space-y-3 border-t border-border pt-3"><h3 className="break-all text-sm font-medium">{run.experiment_id} / {run.id}</h3>
        <p className="text-sm">{t("forexLab.status")}: {run.status}</p><p className="break-all font-mono text-xs">{run.input_hash}</p>
        {run.status !== "running" && run.result ? <Evaluation result={run.result} /> : <p className="text-sm text-muted-foreground">{t("forexLab.runningUnknown")}</p>}
        <JsonEvidence label={t("forexLab.savedEvidence")} data={run} />
        <button type="button" className={button} disabled={saving} onClick={() => { setMethod(forexLabMethod(run.request)); edit(JSON.stringify(run.request, null, 2)); }}>{t("forexLab.loadInputs")}</button>
      </div>}
    </section>
    <p className="text-xs text-muted-foreground">{t("forexLab.limitations")}</p>
  </section>;
}
