import { useEffect, useRef, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";

export const researchButton = "rounded-md border border-border px-3 py-2 text-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";
export const researchField = "w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";

export function parseResearchObject(text: string): Record<string, unknown> {
  if (new TextEncoder().encode(text).byteLength > 64000) throw new Error("Request exceeds 64000 bytes");
  const value: unknown = JSON.parse(text);
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("A JSON object is required");
  return value as Record<string, unknown>;
}

export function ResearchJsonInput({ text, onChange, onError, example, disabled = false }: {
  text: string; onChange: (text: string) => void; onError: (message: string) => void; example: string; disabled?: boolean;
}) {
  const { t } = useTranslation();
  const generation = useRef(0);
  const locked = useRef(disabled);
  locked.current = disabled;
  useEffect(() => { generation.current++; return () => { generation.current++; }; }, [text, example, disabled]);
  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; event.target.value = "";
    if (!file || locked.current) return;
    const id = ++generation.current;
    if (file.size > 64000) { onError(t("valuationLab.invalidInput")); return; }
    try { const input = await file.text(); parseResearchObject(input); if (id === generation.current && !locked.current) onChange(input); }
    catch { if (id === generation.current && !locked.current) onError(t("valuationLab.invalidInput")); }
  }
  return <div className="space-y-3">
    <div className="flex flex-wrap items-center gap-3"><label className={`${researchButton} cursor-pointer`}>{t("valuationLab.import")}<input type="file" className="sr-only" aria-label={t("valuationLab.import")} accept=".json,application/json" disabled={disabled} onChange={(event) => { void upload(event); }} /></label>
      <button type="button" className={researchButton} disabled={disabled} onClick={() => { generation.current++; onChange(example); }}>{t("valuationLab.example")}</button></div>
    <p className="text-xs text-amber-700 dark:text-amber-300">{t("valuationLab.synthetic")}</p>
    <label className="block space-y-1 text-xs font-medium"><span>{t("valuationLab.input")}</span><textarea className={`${researchField} min-h-56 font-mono text-xs`} maxLength={64000} value={text} disabled={disabled} onChange={(event) => { generation.current++; onChange(event.target.value); }} spellCheck={false} dir="ltr" /></label>
  </div>;
}

export function ResearchJsonEvidence({ label, data }: { label: string; data: unknown }) {
  return <details className="rounded-md border border-border p-3"><summary className="cursor-pointer text-sm font-medium">{label}</summary><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all rounded bg-muted/30 p-3 text-xs" dir="ltr">{JSON.stringify(data, null, 2)}</pre></details>;
}
