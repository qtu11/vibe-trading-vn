import { authHeaders } from "./apiAuth";
import { escapeHtml } from "./escapeHtml";

export type ForexFrame = "5m" | "1h" | "4h" | "1d";
export interface ForexCandle { time: string; open: number; high: number; low: number; close: number; volume: number; complete: boolean }
export interface PriceActionEvidence {
  version: 1; status: "ok" | "insufficient"; closed_count: number; as_of?: string;
  patterns: Array<{ name: string; bias: string; time: string; confirmed_bar: boolean }>;
  structure: string; breakout?: string; support_20?: number; resistance_20?: number;
  bullish_close_above?: number; bearish_close_below?: number; forming_candle_used?: boolean;
}
export interface ForexChartSnapshot {
  version: 1; source: "mt5"; symbol: string; connection_id: string; binding_hash: string;
  broker_server: string; environment: "demo" | "live"; timeframe: ForexFrame; retrieved_at: string;
  refresh_interval_seconds: number; volume_unit: "tick_count"; trading_performed: false;
  quote: { bid: string; ask: string; timestamp: string; is_fresh: boolean; age_seconds: number; max_age_seconds: number };
  bars: ForexCandle[]; forming_bar_time: string | null; price_action: PriceActionEvidence;
}

export async function fetchForexChart(connection: string, symbol: string, frame: ForexFrame, signal: AbortSignal): Promise<ForexChartSnapshot> {
  const query = new URLSearchParams({ connection_id: connection, symbol, timeframe: frame, limit: "200" });
  const response = await fetch(`/api/forex/chart?${query}`, { headers: authHeaders(), signal });
  const data = await response.json();
  if (!response.ok) throw new Error(data?.detail?.error || "Cannot read native MT5 candles");
  if (data?.version !== 1 || data.source !== "mt5" || data.symbol !== symbol || data.connection_id !== connection
    || data.timeframe !== frame || data.trading_performed !== false || !/^[a-f0-9]{64}$/.test(data.binding_hash)
    || !Array.isArray(data.bars) || data.bars.length === 0 || data.bars.length > 300
    || !Number.isFinite(Date.parse(data.quote?.timestamp)) || !Number.isFinite(Number(data.quote?.bid))
    || Number(data.quote?.bid) <= 0 || Number(data.quote?.ask) < Number(data.quote?.bid)
    || !Number.isFinite(Number(data.quote?.ask)) || !data.price_action || !Array.isArray(data.price_action.patterns)) {
    throw new Error("Invalid or mismatched broker chart response");
  }
  let previous = -Infinity;
  for (const b of data.bars) {
    const t = Date.parse(b.time);
    if (!Number.isFinite(t) || t <= previous || typeof b.complete !== "boolean"
      || ![b.open, b.high, b.low, b.close].every(v => typeof v === "number" && Number.isFinite(v) && v > 0)
      || b.low > Math.min(b.open, b.close) || b.high < Math.max(b.open, b.close)
      || !Number.isInteger(b.volume) || b.volume < 0) throw new Error("Invalid native candle sequence");
    previous = t;
  }
  return data;
}

export const forexFrameLabel = (frame: string) => ({ "5m": "M5", "1h": "H1", "4h": "H4", "1d": "D1" }[frame] || frame);
export const patternLabel = (name: string) => ({ doji_shape: "Doji", hammer_shape: "Hammer", shooting_star_shape: "Shooting star",
  bullish_engulfing_shape: "Bullish engulfing", bearish_engulfing_shape: "Bearish engulfing", inside_bar: "Inside bar" }[name] || name);

export function forexCandleTooltip(params: unknown): string {
  const points = params as Array<{ axisValue: string; seriesId: string; data: { value?: number[] } | number[] }>;
  const point = Array.isArray(points) ? points.find(p => p.seriesId === "candles") : undefined;
  if (!point) return "";
  const raw = Array.isArray(point.data) ? point.data : point.data?.value;
  if (!Array.isArray(raw) || raw.length < 4) return "";
  // ECharts may prepend the category coordinate to the four OHLC dimensions.
  const [open, close, low, high] = raw.slice(-4);
  if (![open, close, low, high].every(v => Number.isFinite(v) && v > 0)
    || low > Math.min(open, close) || high < Math.max(open, close)) return "";
  return `${escapeHtml(String(point.axisValue))} UTC<br/>O ${open} · H ${high}<br/>L ${low} · C ${close}`;
}
