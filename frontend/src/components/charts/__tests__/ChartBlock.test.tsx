import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ChartBlock, parsePriceChartSpec, toPriceBars } from "../ChartBlock";
import { echarts } from "@/lib/echarts";

// ECharts needs a canvas; the mocked instance is enough to prove the block
// renders while the parse contract is tested independently below.
vi.mock("@/lib/echarts", () => ({
  echarts: {
    init: vi.fn(() => ({
      setOption: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
      group: "",
    })),
  },
  CHART_GROUP: "quant-charts",
  connectCharts: vi.fn(),
}));

function spec(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    type: "candlestick",
    symbol: "FPT.VN",
    venue: "Vietnam",
    currency: "VND",
    interval: "1D",
    source: "yahoo",
    adjustment: "split_dividend",
    as_of: "2026-09-30",
    bars: [
      { t: "2026-09-28", o: 70, h: 72, l: 69, c: 71.5, v: 1_000_000 },
      { t: "2026-09-29", o: 71.5, h: 73, l: 71, c: 72.5, v: 1_100_000 },
      { t: "2026-09-30", o: 72.5, h: 74, l: 72, c: 73.5, v: 900_000 },
    ],
    ...overrides,
  };
}

describe("parsePriceChartSpec", () => {
  it("parses a complete spec and keeps the metadata a reader needs", () => {
    const parsed = parsePriceChartSpec(JSON.stringify(spec()));

    expect(parsed).not.toBeNull();
    expect(parsed?.symbol).toBe("FPT.VN");
    expect(parsed?.currency).toBe("VND");
    expect(parsed?.source).toBe("yahoo");
    expect(parsed?.adjustment).toBe("split_dividend");
    expect(parsed?.bars).toHaveLength(3);
    expect(parsed?.bars[2]).toEqual({
      t: "2026-09-30",
      o: 72.5,
      h: 74,
      l: 72,
      c: 73.5,
      v: 900_000,
    });
  });

  it("returns null for malformed JSON so the fence falls back to code", () => {
    expect(parsePriceChartSpec("```chart")).toBeNull();
    expect(parsePriceChartSpec("")).toBeNull();
    expect(parsePriceChartSpec("null")).toBeNull();
    expect(parsePriceChartSpec("[1,2,3]")).toBeNull();
  });

  it("rejects a spec missing a symbol or a usable bar", () => {
    expect(parsePriceChartSpec(JSON.stringify(spec({ symbol: "" })))).toBeNull();
    expect(parsePriceChartSpec(JSON.stringify(spec({ bars: [] })))).toBeNull();
    expect(
      parsePriceChartSpec(JSON.stringify(spec({ bars: [{ t: "2026-09-30" }] }))),
    ).toBeNull();
    expect(
      parsePriceChartSpec(
        JSON.stringify(spec({ bars: [{ t: "2026-09-30", o: 1, h: 2, l: 0.5, c: null }] })),
      ),
    ).toBeNull();
  });

  it("rejects non-finite prices rather than drawing a broken candle", () => {
    const raw = JSON.stringify(spec()).replace('"c":73.5', '"c":1e999');

    expect(parsePriceChartSpec(raw)).toBeNull();
  });

  it("rejects out-of-order bars", () => {
    const bars = spec().bars as Array<Record<string, unknown>>;
    expect(
      parsePriceChartSpec(JSON.stringify(spec({ bars: [bars[1], bars[0], bars[2]] }))),
    ).toBeNull();
  });

  it("rejects a payload larger than the render budget", () => {
    const bars = Array.from({ length: 1_501 }, (_, index) => ({
      t: `2026-01-01T00:00:${String(index % 60).padStart(2, "0")}`,
      o: 1,
      h: 2,
      l: 0.5,
      c: 1.5,
    }));

    expect(parsePriceChartSpec(JSON.stringify(spec({ bars })))).toBeNull();
  });
});

describe("ChartBlock", () => {
  it("renders the chart with its source metadata", () => {
    render(<ChartBlock code={JSON.stringify(spec())} />);

    expect(screen.getByText(/FPT\.VN/)).toHaveTextContent(
      "FPT.VN · Vietnam · VND · as of 2026-09-30 · yahoo · split_dividend",
    );
    expect(document.querySelector("figure")).not.toBeNull();
  });

  it("shows an unavailable state instead of dumping broken chart JSON", () => {
    render(<ChartBlock code={"not json at all"} />);

    expect(screen.getByRole("status")).toHaveTextContent(/no complete OHLC/i);
    expect(screen.queryByText("not json at all")).toBeNull();
    expect(document.querySelector("figure")).toBeNull();
  });

  it("explains that a legacy chart was redacted instead of showing generic no-data", () => {
    render(
      <ChartBlock
        code={'{"type":"candlestick","symbol":"MBB.VN","as_of":"2025-11-(đã lược※)","bars":[]}'}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(/cannot be reconstructed/);
    expect(screen.queryByText(/no complete OHLC/i)).toBeNull();
    expect(document.querySelector("figure")).toBeNull();
  });

  it("links the exact source and shows historical timing and units", () => {
    const source = "https://query1.finance.yahoo.com/v8/finance/chart/MBB.VN?interval=1d";
    render(<ChartBlock code={JSON.stringify(spec({ source_url: source, retrieved_at: "2026-11-07T16:32:43+00:00", volume_unit: "shares" }))} />);
    expect(screen.getByRole("link", { name: /Data source/ })).toHaveAttribute("href", source);
    expect(screen.getByText(/not a live last-trade quote/)).toBeInTheDocument();
    expect(screen.getByText(/2026-11-07T16:32:43/)).toBeInTheDocument();
    expect(screen.getByText(/Volume unit: shares/)).toBeInTheDocument();
  });

  it("rejects unsafe source URLs and impossible candles", () => {
    expect(parsePriceChartSpec(JSON.stringify(spec({ source_url: "javascript:alert(1)" })))?.source_url).toBeNull();
    expect(parsePriceChartSpec(JSON.stringify(spec({ source_url: "https://user:password@example.com" })))?.source_url).toBeNull();
    expect(parsePriceChartSpec(JSON.stringify(spec({ bars: [{ t: "2026-11-06", o: 10, h: 2, l: 1, c: 12 }] })))).toBeNull();
  });

  it("renders an honest no-data state for a failed tool fetch", () => {
    render(<ChartBlock code={JSON.stringify({ type: "candlestick", symbol: "MBB.VN", status: "unavailable", bars: [] })} />);
    expect(screen.getByRole("status")).toHaveTextContent("MBB.VN");
    expect(document.querySelector("figure")).toBeNull();
  });

  it("shortens daily axis labels while retaining the full observed timestamp", () => {
    const bars = [{ t: "2026-11-06T00:00:00", o: 19000, h: 19350, l: 19000, c: 19250, v: 12496300 }];
    render(<ChartBlock code={JSON.stringify(spec({ bars }))} />);
    const chart = vi.mocked(echarts.init).mock.results.at(-1)?.value;
    const option = chart.setOption.mock.calls.at(-1)[0];
    expect(option.xAxis[0].axisLabel.formatter(bars[0].t)).toBe("2026-11-06");
    expect(option.xAxis[0].data[0]).toBe(bars[0].t);
  });

  it("keeps missing volume unavailable while still drawing valid OHLC candles", () => {
    const bars = [{ t: "2026-11-06", o: 19000, h: 19350, l: 19000, c: 19250 }];
    const parsed = parsePriceChartSpec(JSON.stringify(spec({ bars })))!;
    expect(Number.isNaN(toPriceBars(parsed)[0].volume)).toBe(true);
    render(<ChartBlock code={JSON.stringify(spec({ bars }))} />);
    expect(document.querySelector("figure")).not.toBeNull();
    expect(screen.getByText(/missing values are not zero/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "vol" })).toBeDisabled();
    const option = vi.mocked(echarts.init).mock.results.at(-1)?.value.setOption.mock.calls.at(-1)[0];
    expect(option.series.some((series: { name: string }) => series.name === "Vol")).toBe(false);
  });

  it("draws gaps for partial volume and preserves an observed zero", () => {
    const bars = [
      { t: "2026-11-05", o: 19000, h: 19350, l: 19000, c: 19250 },
      { t: "2026-11-06", o: 19000, h: 19350, l: 19000, c: 19250, v: 0 },
    ];
    render(<ChartBlock code={JSON.stringify(spec({ bars }))} />);
    expect(screen.getByRole("button", { name: "vol" })).toBeEnabled();
    const option = vi.mocked(echarts.init).mock.results.at(-1)?.value.setOption.mock.calls.at(-1)[0];
    const volume = option.series.find((series: { name: string }) => series.name === "Vol");
    expect(volume.data.map((point: { value: number | null }) => point.value)).toEqual([null, 0]);
    expect(option.tooltip.formatter([{ axisValue: "2026-11-05", seriesName: "Vol", value: null }])).not.toContain("Vol:");
  });

  it.each([1, 7])("uses calendar dates for the 1M range on %s-day candles", (step) => {
    const end = Date.parse("2026-11-06T00:00:00Z");
    const bars = Array.from({ length: 100 }, (_, index) => ({ t: new Date(end - (99 - index) * step * 86_400_000).toISOString(), o: 19000, h: 19350, l: 19000, c: 19250, v: 100 }));
    render(<ChartBlock code={JSON.stringify(spec({ bars }))} />);
    fireEvent.click(screen.getByRole("button", { name: "1M", exact: true }));
    const option = vi.mocked(echarts.init).mock.results.at(-1)?.value.setOption.mock.calls.at(-1)[0];
    const first = bars.findIndex((bar) => Date.parse(bar.t) >= Date.parse("2026-10-06T00:00:00Z"));
    expect(option.dataZoom[0].startValue).toBe(first);
    expect(option.dataZoom[0].endValue).toBe(bars.length - 1);
    expect(option.dataZoom[1].startValue).toBe(first);
    if (step === 7) expect(bars.length - first).toBe(5);
  });

  it("clamps calendar month-end and preserves the source timestamp offset", () => {
    const bars = ["2026-02-27T23:59:00+07:00", "2026-02-28T00:00:00+07:00", "2026-03-31T00:00:00+07:00"].map((t) => ({ t, o: 19000, h: 19350, l: 19000, c: 19250 }));
    render(<ChartBlock code={JSON.stringify(spec({ bars }))} />);
    fireEvent.click(screen.getByRole("button", { name: "1M", exact: true }));
    const option = vi.mocked(echarts.init).mock.results.at(-1)?.value.setOption.mock.calls.at(-1)[0];
    expect(option.dataZoom[0].startValue).toBe(1);
  });

  it("keeps an invalid range anchor from producing an invalid zoom", () => {
    const bars = ["invalid-a", "invalid-b"].map((t) => ({ t, o: 19000, h: 19350, l: 19000, c: 19250 }));
    render(<ChartBlock code={JSON.stringify(spec({ bars }))} />);
    fireEvent.click(screen.getByRole("button", { name: "1M", exact: true }));
    const option = vi.mocked(echarts.init).mock.results.at(-1)?.value.setOption.mock.calls.at(-1)[0];
    expect(option.dataZoom[0].startValue).toBe(0);
    expect(option.dataZoom[0].endValue).toBe(1);
  });

  it("keeps MACD warmup values null while preserving a computed zero", () => {
    const bars = Array.from({ length: 40 }, (_, index) => ({ t: new Date(Date.UTC(2026, 8, index + 1)).toISOString(), o: 19000, h: 19350, l: 19000, c: 19250 }));
    render(<ChartBlock code={JSON.stringify(spec({ bars }))} />);
    const option = vi.mocked(echarts.init).mock.results.at(-1)?.value.setOption.mock.calls.at(-1)[0];
    const histogram = option.series.find((series: { name: string }) => series.name === "MACD");
    expect(histogram.data[0]).toBeNull();
    expect(histogram.data[32]).toBeNull();
    expect(histogram.data[33].value).toBe(0);
  });
});
