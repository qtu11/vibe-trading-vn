import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { ForexResearchLab } from "@/components/forex/ForexResearchLab";
import { ForexRegimeLab } from "@/components/forex/ForexRegimeLab";
import { VietnamValuationLab } from "@/components/research/VietnamValuationLab";
import { VietnamReverseDCFLab } from "@/components/research/VietnamReverseDCFLab";
import { CryptoBasisLab } from "@/components/research/CryptoBasisLab";
import { ResearchRevisionPanel } from "@/components/research/ResearchRevisionPanel";
import { evidenceUrl, object, type CryptoRequest, type ResearchObject, type ResearchResult, type ResearchValue, type VietnamRequest } from "@/lib/research";

const control = "w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";
const button = "rounded-md border border-border px-4 py-2 text-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";
const title = (key: string) => key.replace(/_/g, " ").replace(/\./g, " · ");

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="space-y-1 text-xs font-medium text-muted-foreground"><span>{label}</span>{children}</label>;
}

function show(value: ResearchValue | undefined, unknown: string): string {
  if (value === null || value === undefined) return unknown;
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function ValueTable({ values, caption }: { values: ResearchObject; caption: string }) {
  const { t } = useTranslation();
  const rows: [string, ResearchValue][] = [];
  function visit(data: ResearchObject, prefix = "") {
    Object.entries(data).forEach(([key, value]) => {
      const name = prefix + key;
      const item = object(value);
      if (value !== null && typeof value === "object" && !Array.isArray(value) && !("value" in item)) visit(item, name + ".");
      else rows.push([name, value]);
    });
  }
  visit(values);
  return <div className="overflow-x-auto rounded-md border border-border"><table className="w-full text-start text-xs">
    <caption className="p-3 text-start text-sm font-medium">{caption}</caption>
    <thead className="border-y border-border bg-muted/40"><tr>
      {(["indicator", "value", "unit", "reason"] as const).map((key) => <th key={key} scope="col" className="px-3 py-2 text-start font-medium">{t(`marketResearch.${key}`)}</th>)}
    </tr></thead>
    <tbody>{rows.map(([key, value]) => {
      const item = object(value);
      const fact = "value" in item;
      return <tr key={key} className="border-b border-border/50 last:border-0">
        <th scope="row" className="max-w-xs px-3 py-2 text-start font-normal">{title(key)}</th>
        <td className="max-w-md break-words px-3 py-2 font-mono tabular-nums">{show(fact ? item.value : value, t("marketResearch.unknown"))}</td>
        <td className="px-3 py-2">{fact ? show(item.unit, "—") : "—"}</td>
        <td className="max-w-sm break-words px-3 py-2 text-muted-foreground">{fact ? [item.reason, Array.isArray(item.evidence) ? item.evidence.join(", ") : null].filter(Boolean).join(" · ") || "—" : "—"}</td>
      </tr>;
    })}</tbody>
  </table></div>;
}

function Evidence({ rows }: { rows: ResearchObject[] }) {
  const { t } = useTranslation();
  return <details className="rounded-md border border-border p-3">
    <summary className="cursor-pointer text-sm font-medium">{t("marketResearch.evidence")} ({rows.length})</summary>
    <div className="mt-3 space-y-3">{rows.map((row, index) => {
      const url = evidenceUrl(row.source_url);
      return <div key={index} className="space-y-2 rounded-md bg-muted/30 p-3 text-xs">
        <p className="break-all">{show(row.id, "")} · {url ? <a href={url} target="_blank" rel="noopener noreferrer" className="text-primary underline">{show(row.source_url, "")}</a> : t("marketResearch.invalidSource")}</p>
        <ValueTable values={Object.fromEntries(Object.entries(row).filter(([key]) => !["source_url", "id"].includes(key)))} caption={show(row.locator, t("marketResearch.evidence"))} />
      </div>;
    })}</div>
  </details>;
}

function VietnamResult({ result, onNext, disabled = false }: { result: ResearchResult; onNext: () => void; disabled?: boolean }) {
  const { t } = useTranslation();
  return <div className="space-y-4">{Object.entries(result.data ?? {}).map(([code, company]) => {
    const periods = Array.isArray(company.periods) ? company.periods.map(object) : [];
    return <div key={code} className="space-y-4">
      <h2 className="text-lg font-semibold">{code} · {show(company.venue, t("marketResearch.unknown"))}</h2>
      <p className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-sm">{t("marketResearch.unverified")}</p>
      <ValueTable values={Object.fromEntries(Object.entries(company).filter(([key]) => key !== "periods"))} caption={t("marketResearch.provenance")} />
      {periods.length === 0 && <p>{t("marketResearch.empty")}</p>}
      {periods.map((period) => <section key={String(period.period_end)} className="space-y-3 rounded-lg border border-border bg-card p-4">
        <h3 className="font-medium">{show(period.period_start, t("marketResearch.unknown"))} → {show(period.period_end, t("marketResearch.unknown"))}</h3>
        <p className="text-xs text-muted-foreground">{t("marketResearch.balanceCheck")}: {show(object(period.checks).balance_sheet, t("marketResearch.unknown"))}</p>
        <ValueTable values={object(period.metrics)} caption={t("marketResearch.metrics")} />
        <details><summary className="cursor-pointer text-sm">{t("marketResearch.inputs")}</summary><div className="mt-2"><ValueTable values={object(period.inputs)} caption={t("marketResearch.inputs")} /></div></details>
        <Evidence rows={Array.isArray(period.evidence) ? period.evidence.map(object) : []} />
      </section>)}
    </div>;
  })}
    {result.paging && <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
      <span>{t("marketResearch.page", { start: result.paging.returned ? result.paging.offset + 1 : 0, end: result.paging.offset + result.paging.returned, total: result.paging.total })}</span>
      {result.paging.next_offset !== null && <button type="button" className={button} disabled={disabled} onClick={onNext}>{t("marketResearch.next")}</button>}
    </div>}
    {(result.limitations ?? []).map((line) => <p key={line} className="text-xs text-muted-foreground">{line}</p>)}
  </div>;
}

function CryptoResult({ result }: { result: ResearchResult }) {
  const { t } = useTranslation();
  const url = evidenceUrl(result.provenance?.reference);
  return <div className="space-y-4">
    <h2 className="text-lg font-semibold">{result.symbol} · {title(result.metric ?? "")}</h2>
    <p className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-sm">{t("marketResearch.cryptoLimits")}</p>
    <ValueTable values={result.summary ?? {}} caption={t("marketResearch.summary")} />
    {result.archive && <ValueTable values={result.archive} caption={t("marketResearch.archiveReceipt")} />}
    <div className="grid gap-4 xl:grid-cols-2">
      <ValueTable values={result.coverage ?? {}} caption={t("marketResearch.coverage")} />
      <ValueTable values={{ ...result.provenance, ...result.units, ...result.display }} caption={t("marketResearch.provenance")} />
    </div>
    {url && <a href={url} target="_blank" rel="noopener noreferrer" className="inline-block text-sm text-primary underline">{t("marketResearch.providerReference")}</a>}
    <details><summary className="cursor-pointer text-sm font-medium">{t("marketResearch.observations")}</summary>
      <div className="mt-3 space-y-3">{(result.observations ?? []).map((row, index) => <ValueTable key={index} values={row} caption={show(row.event_time, String(index + 1))} />)}</div>
    </details>
  </div>;
}

export function MarketResearch() {
  const { t } = useTranslation();
  const [market, setMarket] = useState<"vn" | "crypto" | "forex">("vn");
  const [vnWorkflow, setVnWorkflow] = useState<"statements" | "valuation" | "reverse_dcf">("statements");
  const [cryptoWorkflow, setCryptoWorkflow] = useState<"derivatives" | "basis">("derivatives");
  const [forexWorkflow, setForexWorkflow] = useState<"lab" | "regime">("lab");
  const [revisionWriting, setRevisionWriting] = useState(false);
  const [vn, setVn] = useState<VietnamRequest>({ code: "", as_of: "", period: "quarter", consolidation: "consolidated", offset: 0 });
  const [crypto, setCrypto] = useState<CryptoRequest>({ symbol: "", metric: "open_interest", period: "1h", limit: 30, mode: "live", as_of: "" });
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const capturePending = useRef(false);
  const generation = useRef(0);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => { generation.current++; pending.current?.abort(); }, []);

  function clear() {
    generation.current++;
    pending.current?.abort();
    pending.current = null;
    setLoading(false);
    setResult(null);
    setError("");
  }
  async function run(nextOffset = 0) {
    const previous = result;
    clear();
    if (market === "vn" && !/^[A-Z0-9]{1,12}\.VN$/.test(vn.code.trim().toUpperCase())) {
      setError(t("marketResearch.invalidListing")); return;
    }
    if (market === "vn" && vn.as_of && (!/[T ].*(?:Z|[+-]\d{2}:\d{2})$/.test(vn.as_of) || !Number.isFinite(Date.parse(vn.as_of)))) {
      setError(t("marketResearch.invalidCutoff")); return;
    }
    if (market === "crypto" && !/^[A-Z0-9]{1,30}-USDT-PERP$/.test(crypto.symbol.trim().toUpperCase())) {
      setError(t("marketResearch.invalidPerpetual")); return;
    }
    if (market === "crypto" && crypto.mode === "archive" && (!crypto.as_of || !/[T ].*(?:Z|[+-]\d{2}:\d{2})$/.test(crypto.as_of) || !Number.isFinite(Date.parse(crypto.as_of)))) {
      setError(t("marketResearch.archiveCutoffRequired")); return;
    }
    const id = generation.current;
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    try {
      // Freeze the declared cutoff while paging; never silently advance to now.
      const company = Object.values(previous?.data ?? {})[0];
      const cutoff = nextOffset > 0 ? company?.as_of : vn.as_of;
      const payload = { ...vn, code: vn.code.trim().toUpperCase(), as_of: typeof cutoff === "string" && cutoff ? cutoff : undefined, offset: nextOffset };
      const response = market === "vn" ? await api.researchVietnam(payload, controller.signal)
        : await api.researchCrypto({ ...crypto, symbol: crypto.symbol.trim().toUpperCase(), as_of: crypto.mode === "archive" ? crypto.as_of : undefined }, controller.signal);
      if (id !== generation.current) return;
      if (!response.ok) setError(response.error || t("marketResearch.failed"));
      else setResult(response);
    } catch (reason) {
      if (id === generation.current && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : t("marketResearch.failed"));
    } finally {
      if (id === generation.current) { setLoading(false); pending.current = null; }
    }
  }
  async function capture() {
    if (capturePending.current) return;
    clear();
    if (!/^[A-Z0-9]{1,30}-USDT-PERP$/.test(crypto.symbol.trim().toUpperCase())) { setError(t("marketResearch.invalidPerpetual")); return; }
    capturePending.current = true; setCapturing(true);
    const id = generation.current;
    try {
      const response = await api.captureCrypto({ symbol: crypto.symbol.trim().toUpperCase(), metric: crypto.metric, period: crypto.period, limit: crypto.limit });
      if (id !== generation.current) return;
      if (!response.ok) setError(response.error || t("marketResearch.failed")); else setResult(response);
    } catch (reason) {
      if (id === generation.current) setError(`${reason instanceof Error ? reason.message : t("marketResearch.failed")} ${t("marketResearch.captureUncertain")}`);
    } finally { capturePending.current = false; if (id === generation.current) setCapturing(false); }
  }
  function submit(event: FormEvent) { event.preventDefault(); void run(); }
  function changeVn(patch: Partial<VietnamRequest>) { clear(); setVn((previous) => ({ ...previous, ...patch })); }
  function changeCrypto(patch: Partial<CryptoRequest>) { clear(); setCrypto((previous) => ({ ...previous, ...patch })); }

  return <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-6">
    <header className="space-y-2"><h1 className="text-2xl font-semibold">{t("marketResearch.title")}</h1><p className="max-w-3xl text-sm text-muted-foreground">{t("marketResearch.description")}</p></header>
    <div className="max-w-sm"><Field label={t("marketResearch.market")}><select className={control} disabled={capturing || revisionWriting} value={market} onChange={(event) => { clear(); setMarket(event.target.value as typeof market); }}>
      <option value="vn">{t("marketResearch.vn")}</option><option value="crypto">{t("marketResearch.crypto")}</option><option value="forex">{t("forexLab.title")}</option>
    </select></Field></div>
    {market === "vn" && <div className="max-w-sm"><Field label={t("valuationLab.workflow")}><select className={control} disabled={revisionWriting} value={vnWorkflow} onChange={(event) => { clear(); setVnWorkflow(event.target.value as typeof vnWorkflow); }}><option value="statements">{t("valuationLab.statements")}</option><option value="valuation">{t("valuationLab.title")}</option><option value="reverse_dcf">{t("reverseDCF.title")}</option></select></Field></div>}
    {market === "crypto" && <div className="max-w-sm"><Field label={t("cryptoBasis.workflow")}><select className={control} disabled={capturing || revisionWriting} value={cryptoWorkflow} onChange={(event) => { clear(); setCryptoWorkflow(event.target.value as typeof cryptoWorkflow); }}><option value="derivatives">{t("cryptoBasis.derivatives")}</option><option value="basis">{t("cryptoBasis.title")}</option></select></Field></div>}
    {market === "forex" && <div className="max-w-sm"><Field label={t("forexRegime.workflow")}><select className={control} disabled={revisionWriting} value={forexWorkflow} onChange={(event) => { clear(); setForexWorkflow(event.target.value as typeof forexWorkflow); }}><option value="lab">{t("forexRegime.lab")}</option><option value="regime">{t("forexRegime.regime")}</option></select></Field></div>}
    {market === "forex" ? forexWorkflow === "regime" ? <ForexRegimeLab /> : <ForexResearchLab onBusyChange={setRevisionWriting} /> : market === "vn" && vnWorkflow === "valuation" ? <VietnamValuationLab /> : market === "vn" && vnWorkflow === "reverse_dcf" ? <VietnamReverseDCFLab onBusyChange={setRevisionWriting} /> : market === "crypto" && cryptoWorkflow === "basis" ? <CryptoBasisLab onBusyChange={setRevisionWriting} /> : <form onSubmit={submit} className="space-y-4 rounded-lg border border-border bg-card p-4">
      {market === "vn" ? <>
        <p className="text-xs text-muted-foreground">{t("marketResearch.vnSetup")}</p>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Field label={t("marketResearch.code")}><input className={control} disabled={revisionWriting} required maxLength={15} placeholder="FPT.VN" value={vn.code} onChange={(event) => changeVn({ code: event.target.value })} /></Field>
          <Field label={t("marketResearch.asOf")}><input className={control} disabled={revisionWriting} maxLength={64} placeholder="2025-08-01T00:00:00Z" value={vn.as_of} onChange={(event) => changeVn({ as_of: event.target.value })} /></Field>
          <Field label={t("marketResearch.period")}><select className={control} disabled={revisionWriting} value={vn.period} onChange={(event) => changeVn({ period: event.target.value as VietnamRequest["period"] })}><option value="quarter">{t("marketResearch.quarter")}</option><option value="annual">{t("marketResearch.annual")}</option></select></Field>
          <Field label={t("marketResearch.scope")}><select className={control} disabled={revisionWriting} value={vn.consolidation} onChange={(event) => changeVn({ consolidation: event.target.value as VietnamRequest["consolidation"] })}><option value="consolidated">{t("marketResearch.consolidated")}</option><option value="separate">{t("marketResearch.separate")}</option></select></Field>
        </div>
      </> : <>
        <p className="text-xs text-muted-foreground">{t("marketResearch.cryptoSetup")}</p>
        <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
          <Field label={t("marketResearch.cryptoMode")}><select className={control} disabled={capturing} value={crypto.mode} onChange={(event) => changeCrypto({ mode: event.target.value as CryptoRequest["mode"] })}><option value="live">{t("marketResearch.cryptoLive")}</option><option value="archive">{t("marketResearch.cryptoArchive")}</option></select></Field>
          {crypto.mode === "archive" && <Field label={t("marketResearch.cryptoCutoff")}><input className={control} required maxLength={64} placeholder="2026-11-06T00:00:00Z" value={crypto.as_of} onChange={(event) => changeCrypto({ as_of: event.target.value })} /></Field>}
        </div>
        {crypto.mode === "archive" && <p className="text-xs text-muted-foreground">{t("marketResearch.archiveSetup")}</p>}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Field label={t("marketResearch.symbol")}><input className={control} disabled={capturing} required maxLength={40} placeholder="BTC-USDT-PERP" value={crypto.symbol} onChange={(event) => changeCrypto({ symbol: event.target.value })} /></Field>
          <Field label={t("marketResearch.metric")}><select className={control} disabled={capturing} value={crypto.metric} onChange={(event) => changeCrypto({ metric: event.target.value as CryptoRequest["metric"] })}><option value="open_interest">Open Interest</option><option value="funding">Funding</option></select></Field>
          <Field label={t("marketResearch.sampling")}><select className={control} disabled={capturing || crypto.metric === "funding"} value={crypto.period} onChange={(event) => changeCrypto({ period: event.target.value as CryptoRequest["period"] })}>{["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"].map((period) => <option key={period}>{period}</option>)}</select></Field>
          <Field label={t("marketResearch.limit")}><input className={control} disabled={capturing} required type="number" min={2} max={100} step={1} value={crypto.limit} onChange={(event) => changeCrypto({ limit: event.target.valueAsNumber })} /></Field>
        </div>
      </>}
      <div className="flex flex-wrap items-center gap-3"><button className={`${button} bg-primary/10 text-primary`} disabled={loading || capturing || revisionWriting} type="submit">{loading ? t("marketResearch.loading") : t("marketResearch.run")}</button>
        {loading && <button type="button" className={button} onClick={clear}>{t("marketResearch.cancel")}</button>}
        {market === "crypto" && crypto.mode === "live" && <button type="button" className={button} disabled={loading || capturing} onClick={() => { void capture(); }}>{t("marketResearch.capture")}</button>}
      </div>
      {market === "crypto" && crypto.mode === "live" && <p className="text-xs text-muted-foreground">{t("marketResearch.captureExplanation")}</p>}
    </form>}
    {loading && <p role="status" className="text-sm text-muted-foreground">{t("marketResearch.loading")}</p>}
    {capturing && <p role="status" className="text-sm text-muted-foreground">{t("marketResearch.capturing")}</p>}
    {error && <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div>}
    {market !== "forex" && !(market === "vn" && vnWorkflow !== "statements") && !(market === "crypto" && cryptoWorkflow === "basis") && !result && !loading && !error && <p className="text-sm text-muted-foreground">{t("marketResearch.initial")}</p>}
    {result && <div aria-live="polite">{market === "vn" ? <VietnamResult result={result} disabled={revisionWriting} onNext={() => { void run(result.paging?.next_offset ?? 0); }} /> : <CryptoResult result={result} />}</div>}
    {market === "vn" && vnWorkflow === "statements" && <ResearchRevisionPanel kind="vietnam" request={result?.data ? { code: vn.code.trim().toUpperCase(), as_of: Object.values(result.data)[0]?.as_of ?? vn.as_of ?? null, period: vn.period, consolidation: vn.consolidation, offset: result.paging?.offset ?? 0 } : null} onBusyChange={setRevisionWriting} />}
  </div>;
}
