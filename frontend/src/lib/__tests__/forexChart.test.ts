import { fetchForexChart, forexCandleTooltip } from "../forexChart";

const fixture = () => ({ version: 1, source: "mt5", symbol: "XAUUSDm", connection_id: "fixture", timeframe: "5m",
  binding_hash: "a".repeat(64), trading_performed: false, price_action: { patterns: [] },
  quote: { bid: "100", ask: "100.1", timestamp: "2026-11-03T00:00:01Z" },
  bars: [{ time: "2026-11-03T00:00:00Z", open: 100, high: 102, low: 99, close: 101, volume: 12, complete: false }] });
afterEach(() => vi.unstubAllGlobals());

it("preserves an actual forming bar and pins request identity/timeframe", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => fixture() });
  vi.stubGlobal("fetch", fetch);
  const result = await fetchForexChart("fixture", "XAUUSDm", "5m", new AbortController().signal);
  expect(result.bars[0].complete).toBe(false);
  expect(result.bars[0].close).toBe(101);
  expect(fetch.mock.calls[0][0]).toContain("connection_id=fixture&symbol=XAUUSDm&timeframe=5m");
});

it.each(["identity", "geometry", "duplicate"])("rejects invalid %s data without inventing candles", async (failure) => {
  const data = fixture();
  if (failure === "identity") data.connection_id = "other";
  else if (failure === "geometry") data.bars[0].high = 90;
  else data.bars.push({ ...data.bars[0] });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => data }));
  await expect(fetchForexChart("fixture", "XAUUSDm", "5m", new AbortController().signal)).rejects.toThrow();
});

it.each([[100, 102, 99, 103], [116, 100, 102, 99, 103]])("shows actual OHLC when ECharts supplies %j", (...value: number[]) => {
  const text = forexCandleTooltip([{ seriesId: "candles", axisValue: "2026-11-03T00:00:00Z", data: { value } }]);
  expect(text).toContain("O 100 · H 103");
  expect(text).toContain("L 99 · C 102");
  expect(text).not.toContain("O 116");
});

it("escapes tooltip time labels and omits malformed candles", () => {
  expect(forexCandleTooltip([{ seriesId: "candles", axisValue: "<img>", data: [100, 102, 99, 103] }])).toContain("&lt;img&gt;");
  expect(forexCandleTooltip([{ seriesId: "candles", axisValue: "UTC", data: [100, 102, 200, 1] }])).toBe("");
});
