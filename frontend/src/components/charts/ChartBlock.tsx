import { memo, useMemo } from "react";
import { CandlestickChart } from "./CandlestickChart";
import type { PriceBar } from "@/lib/api";

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
  adjustment?: string | null;
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
  const bar: PriceChartBar = { t, o: row.o, h: row.h, l: row.l, c: row.c };
  if (isFiniteNumber(row.v)) bar.v = row.v;
  return bar;
}

function textOf(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/**
 * Parse a chart fence. Returns null for anything that is not a complete,
 * finite candlestick spec, so a half-streamed block falls back to code instead
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
    adjustment: textOf(record.adjustment),
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
    volume: bar.v ?? 0,
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

export const ChartBlock = memo(function ChartBlock({ code }: { code: string }) {
  const spec = useMemo(() => parsePriceChartSpec(code), [code]);
  const bars = useMemo(() => (spec ? toPriceBars(spec) : []), [spec]);

  if (!spec) {
    return (
      <pre className="overflow-x-auto rounded-lg border border-border/50 bg-muted/30 p-3 text-[11px] leading-relaxed">
        <code>{code}</code>
      </pre>
    );
  }

  return (
    <figure
      dir="ltr"
      className="my-3 overflow-hidden rounded-xl border border-border/60 bg-card/40 px-3 pt-2 pb-1"
    >
      <figcaption className="mb-1 truncate font-mono text-[11px] text-muted-foreground">
        {metaLine(spec)}
      </figcaption>
      <CandlestickChart data={bars} height={340} />
    </figure>
  );
});

export default ChartBlock;
