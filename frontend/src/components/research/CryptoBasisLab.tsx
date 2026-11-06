import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { object, type ResearchObject, type ResearchValue } from "@/lib/research";
import basisExample from "@/data/research/crypto-basis.example.json?raw";
import { parseResearchObject, researchButton as button, ResearchJsonEvidence, ResearchJsonInput } from "./ResearchJsonInput";
import { ResearchRevisionPanel } from "./ResearchRevisionPanel";

const show = (value: ResearchValue | undefined, missing: string) => value === null || value === undefined ? missing : typeof value === "object" ? JSON.stringify(value) : String(value);

function BasisResult({ result }: { result: ResearchObject }) {
  const { t } = useTranslation();
  const missing = t("marketResearch.unknown"), summary = object(result.summary);
  const rows = Array.isArray(result.rows) ? result.rows.map(object) : [];
  return <section className="space-y-3 rounded-lg border border-border bg-card p-4" aria-label={t("cryptoBasis.result")}>
    <h2 className="text-lg font-semibold">{t("cryptoBasis.result")}</h2>
    <p className="text-xs text-amber-700 dark:text-amber-300">{t("cryptoBasis.grossOnly")}</p>
    <p className="text-xs text-muted-foreground">{t("cryptoBasis.annualization")}</p>
    <p className="text-sm">{show(result.base, missing)}/{show(result.quote, missing)} · {t("cryptoBasis.accepted")}: {show(summary.accepted, missing)} · {t("cryptoBasis.rejected")}: {show(summary.rejected, missing)}</p>
    <div className="overflow-x-auto rounded border border-border"><table className="w-full text-xs">
      <caption className="p-3 text-start">{t("cryptoBasis.contracts")}</caption>
      <thead className="border-y border-border bg-muted/40"><tr>{(["contract", "expiry", "remainingSeconds", "basis", "annualized", "bounds", "status"] as const).map((key) => <th scope="col" key={key} className="whitespace-nowrap px-3 py-2 text-start">{t(`cryptoBasis.${key}`)}</th>)}</tr></thead>
      <tbody>{rows.map((row, index) => <tr key={`${show(row.venue, "")}/${show(row.instrument_id, "")}/${index}`} className="border-b border-border/50 last:border-0">
        <th scope="row" className="min-w-40 max-w-xs break-all px-3 py-2 text-start font-normal">{show(row.venue, missing)} · {show(row.instrument_id, missing)}</th>
        <td className="min-w-36 px-3 py-2">{show(row.expiry, missing)}</td>
        <td className="px-3 py-2 font-mono">{show(row.seconds_to_expiry, missing)}</td>
        <td className="max-w-48 break-all px-3 py-2 font-mono">{show(row.basis_fraction, missing)}</td>
        <td className="max-w-48 break-all px-3 py-2 font-mono">{show(row.annualized_basis, missing)}</td>
        <td className="min-w-44 max-w-64 break-all px-3 py-2 font-mono">{show(row.annualized_lower_basis, missing)} / {show(row.annualized_upper_basis, missing)}</td>
        <td className="min-w-44 max-w-sm break-words px-3 py-2">{row.status === "accepted" ? t("cryptoBasis.accepted") : row.status === "rejected" ? t("cryptoBasis.rejected") : missing}
          {Array.isArray(row.reason_codes) && row.reason_codes.length > 0 && <p className="mt-1 text-muted-foreground">{row.reason_codes.map((reason) => show(reason, missing)).join(" · ")}</p>}</td>
      </tr>)}</tbody>
    </table></div>
    <p className="break-all text-xs text-muted-foreground">{t("cryptoBasis.inputHash")}: {show(result.input_sha256, missing)} · {show(result.verification_status, missing)}</p>
    <ResearchJsonEvidence label={t("cryptoBasis.evidence")} data={result} />
  </section>;
}

export function CryptoBasisLab({ onBusyChange }: { onBusyChange?: (busy: boolean) => void } = {}) {
  const { t } = useTranslation();
  const [text, setText] = useState(""), [result, setResult] = useState<ResearchObject | null>(null), [input, setInput] = useState<ResearchObject | null>(null);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [writing, setWriting] = useState(false);
  const generation = useRef(0), controller = useRef<AbortController | null>(null);
  useEffect(() => () => { generation.current++; controller.current?.abort(); }, []);
  const writingChanged = useCallback((pending: boolean) => { setWriting(pending); onBusyChange?.(pending); }, [onBusyChange]);
  function edit(value: string) { generation.current++; controller.current?.abort(); setText(value); setResult(null); setInput(null); setBusy(false); setError(""); }
  async function evaluate() {
    let payload: ResearchObject;
    try { payload = parseResearchObject(text) as ResearchObject; } catch { setError(t("cryptoBasis.invalidInput")); return; }
    const id = ++generation.current; controller.current?.abort(); const pending = new AbortController(); controller.current = pending;
    setBusy(true); setResult(null); setInput(null); setError("");
    try {
      const response = await api.researchCryptoBasis(payload, pending.signal);
      if (id !== generation.current) return;
      if (response.ok !== true) setError(typeof response.error === "string" ? response.error : t("cryptoBasis.failed"));
      else { setResult(response); setInput(payload); }
    } catch (reason) { if (id === generation.current && !pending.signal.aborted) setError(reason instanceof Error ? reason.message : t("cryptoBasis.failed")); }
    finally { if (id === generation.current) setBusy(false); }
  }
  return <div className="space-y-5">
    <section className="space-y-4 rounded-lg border border-border bg-card p-4">
      <h2 className="text-lg font-semibold">{t("cryptoBasis.title")}</h2><p className="text-sm text-muted-foreground">{t("cryptoBasis.description")}</p>
      <ResearchJsonInput text={text} onChange={edit} onError={setError} example={basisExample} disabled={writing} />
      <div className="flex flex-wrap gap-3"><button type="button" className={button} disabled={!text.trim() || busy || writing} onClick={() => { void evaluate(); }}>{t("cryptoBasis.calculate")}</button>
        {busy && <button type="button" className={button} onClick={() => edit(text)}>{t("marketResearch.cancel")}</button>}</div>
    </section>
    {busy && <p role="status" className="text-sm text-muted-foreground">{t("marketResearch.loading")}</p>}
    {error && <p role="alert" className="rounded border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
    {result && <BasisResult result={result} />}
    <ResearchRevisionPanel kind="crypto_basis" request={input} onBusyChange={writingChanged} />
  </div>;
}
