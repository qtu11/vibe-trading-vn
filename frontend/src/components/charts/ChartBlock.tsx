import { memo, useMemo } from "react";
import { CandlestickChart } from "./CandlestickChart";
import type { PriceBar } from "@/lib/api";
import { hasLegacyGroundingMarker } from "@/lib/legacyGrounding";
import i18n from "@/i18n";

/** One compact bar as the `build_price_chart` tool emits it. */
export interface PriceChartBar {
  t: string;
  o?: number | null;
  h?: number | null;
  l?: number | null;
  c: number;
  v?: number | null;
}

/** The `chart` fenced-block contract. Unknown fields are ignored. */
export interface PriceChartSpec {
  type?: string;
  symbol: string;
  venue?: string | null;
  currency?: string | null;
  interval?: string | null;
  source?: string | null;
  source_url?: string | null;
  adjustment?: string | null;
  price_unit?: string | null;
  volume_unit?: string | null;
  as_of?: string | null;
  retrieved_at?: string | null;
  bars: PriceChartBar[];
}

const MAX_BARS = 1_500;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function parseBar(raw: unknown): PriceChartBar | null {
  if (raw === null || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const t = typeof row.t === "string" ? row.t.trim() : "";
  if (!t || !isFiniteNumber(row.c)) return null;
  if (!isFiniteNumber(row.o) || !isFiniteNumber(row.h) || !isFiniteNumber(row.l)) {
    return null;
  }
  if (row.l > Math.min(row.o, row.c) || row.h < Math.max(row.o, row.c)) return null;
  const bar: PriceChartBar = { t, o: row.o, h: row.h, l: row.l, c: row.c };
  if (isFiniteNumber(row.v) && row.v >= 0) bar.v = row.v;
  return bar;
}

function textOf(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function sourceUrl(value: unknown): string | null {
  const text = textOf(value);
  if (!text) return null;
  try {
    const url = new URL(text);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

/**
 * Parse a chart fence. Returns null for anything that is not a complete,
 * finite candlestick spec, so a half-streamed block shows an unavailable state instead
 * of drawing a misleading chart.
 */
export function parsePriceChartSpec(text: string): PriceChartSpec | null {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return null;
  }
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  const symbol = textOf(record.symbol);
  if (!symbol) return null;
  if (!Array.isArray(record.bars) || record.bars.length === 0) return null;
  if (record.bars.length > MAX_BARS) return null;

  const bars: PriceChartBar[] = [];
  for (const item of record.bars) {
    const bar = parseBar(item);
    if (!bar) return null;
    bars.push(bar);
  }
  for (let index = 1; index < bars.length; index += 1) {
    if (bars[index].t < bars[index - 1].t) return null;
  }

  return {
    type: textOf(record.type) ?? "candlestick",
    symbol,
    venue: textOf(record.venue),
    currency: textOf(record.currency),
    interval: textOf(record.interval),
    source: textOf(record.source),
    source_url: sourceUrl(record.source_url),
    adjustment: textOf(record.adjustment),
    price_unit: textOf(record.price_unit),
    volume_unit: textOf(record.volume_unit),
    as_of: textOf(record.as_of),
    retrieved_at: textOf(record.retrieved_at),
    bars,
  };
}

export function toPriceBars(spec: PriceChartSpec): PriceBar[] {
  return spec.bars.map((bar) => ({
    time: bar.t,
    open: bar.o ?? bar.c,
    high: bar.h ?? bar.c,
    low: bar.l ?? bar.c,
    close: bar.c,
    volume: bar.v ?? Number.NaN,
  }));
}

function metaLine(spec: PriceChartSpec): string {
  return [
    spec.symbol,
    spec.venue,
    spec.currency,
    spec.as_of ? `as of ${spec.as_of}` : null,
    spec.source,
    spec.adjustment,
  ]
    .filter((part): part is string => Boolean(part))
    .join(" · ");
}

/** State the unit explicitly, so "234,500" is read as a price and not a count. */
function unitLine(spec: PriceChartSpec): string | null {
  const parts: string[] = [];
  if (spec.price_unit) parts.push(`Đơn vị giá: ${spec.price_unit}`);
  if (spec.volume_unit) parts.push(`Đơn vị khối lượng: ${spec.volume_unit}`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

export const ChartBlock = memo(function ChartBlock({ code }: { code: string }) {
  const spec = useMemo(() => parsePriceChartSpec(code), [code]);
  const bars = useMemo(() => (spec ? toPriceBars(spec) : []), [spec]);
  const legacyCorrupted = useMemo(() => hasLegacyGroundingMarker(code), [code]);

  if (!spec) {
    let symbol = "";
    try {
      const raw = JSON.parse(code);
      if (raw && typeof raw.symbol === "string") symbol = raw.symbol.slice(0, 80);
    } catch { /* Incomplete streamed data cannot be drawn. */ }
    return (
      <div role="status" className="my-3 rounded-xl border border-border/60 bg-muted/20 p-4 text-sm text-muted-foreground">
        {symbol && <div className="mb-1 font-mono text-xs">{symbol}</div>}
        {i18n.t(legacyCorrupted ? "charts.legacyUnavailable" : "charts.noCompleteBars")}
      </div>
    );
  }

  return (
    <figure
      dir="ltr"
      className="my-3 min-w-0 overflow-hidden rounded-xl border border-border/60 bg-card/40 px-3 pt-2 pb-1"
    >
      <figcaption className="mb-2 space-y-1 text-[11px] text-muted-foreground">
        <div className="break-words font-mono">{metaLine(spec)}</div>
        {unitLine(spec) && <div className="break-words">{unitLine(spec)}</div>}
        <div>{i18n.t("charts.historicalNote")}</div>
        {spec.bars.some((bar) => !isFiniteNumber(bar.v)) && <div>{i18n.t("charts.volumeUnavailable")}</div>}
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {spec.source_url ? <a href={spec.source_url} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2">{i18n.t("charts.sourceLink")}</a> : <span>{i18n.t("charts.sourceUrlUnavailable")}</span>}
          {spec.retrieved_at && <span>{i18n.t("charts.retrievedAt", { value: spec.retrieved_at })}</span>}
          {spec.volume_unit && <span>{i18n.t("charts.volumeUnit", { value: spec.volume_unit })}</span>}
        </div>
      </figcaption>
      <CandlestickChart data={bars} height={420} />
    </figure>
  );
});

export default ChartBlock;
