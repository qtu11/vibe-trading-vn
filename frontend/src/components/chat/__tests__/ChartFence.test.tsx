import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarkdownContent } from "../MessageBubble";

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
vi.mock("../RunCompleteCard", () => ({ RunCompleteCard: () => null }));

function chartSpec(): string {
  return JSON.stringify({
    type: "candlestick",
    symbol: "FPT.VN",
    venue: "Vietnam",
    currency: "VND",
    source: "yahoo",
    as_of: "2026-09-30",
    bars: [
      { t: "2026-09-28", o: 70, h: 72, l: 69, c: 71.5, v: 1_000_000 },
      { t: "2026-09-30", o: 72.5, h: 74, l: 72, c: 73.5, v: 900_000 },
    ],
  });
}

describe("chart fences in an answer", () => {
  it("renders a ```chart fence instead of raw JSON", async () => {
    render(
      <MarkdownContent
        content={"Chart:\n\n```chart\n" + chartSpec() + "\n```\n"}
        streaming
      />,
    );

    expect(await screen.findByText(/FPT\.VN · Vietnam · VND/)).toBeInTheDocument();
    expect(screen.queryByText(chartSpec())).toBeNull();
  });

  it("leaves ordinary fenced code untouched", () => {
    render(<MarkdownContent content={"```python\nprint('hello')\n```\n"} streaming />);

    const code = screen.getByText("print('hello')");
    expect(code.tagName).toBe("CODE");
    expect(code.className).not.toContain("language-chart");
  });
});
