import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChartBlock, parsePriceChartSpec } from "../ChartBlock";

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

  it("falls back to a plain code block when the fence is not valid JSON", () => {
    render(<ChartBlock code={"not json at all"} />);

    expect(screen.getByText("not json at all")).toBeInTheDocument();
    expect(document.querySelector("figure")).toBeNull();
  });
});
