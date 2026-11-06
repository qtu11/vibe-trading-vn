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
vi.mock("../../RunCompleteCard", () => ({ RunCompleteCard: () => null }));

function councilBlock(): string {
  return JSON.stringify({
    type: "council",
    symbol: "FPT.VN",
    snapshot: { source: "yahoo", currency: "VND", as_of: "2026-11-05", bars: 36 },
    verdict: {
      stance: "buy",
      stance_label: "MUA",
      horizon: "3-6 tháng",
      confidence_pct: 68,
      entry_zone: { low: 62000, high: 64000 },
      stop: 59500,
      risks: ["Rủi ro tập trung khách hàng"],
      sources: [],
    },
    evaluation: {},
    issues: [],
    actionable: true,
    trade_actionable: true,
    debate: [],
    sources: [],
    disclaimer: "Khuyến nghị tham khảo.",
  });
}

describe("council fences in an answer", () => {
  it("renders a ```council fence instead of raw JSON", async () => {
    render(
      <MarkdownContent
        content={"Hội đồng:\n\n```council\n" + councilBlock() + "\n```\n"}
        streaming
      />,
    );

    expect(await screen.findByText("MUA")).toBeInTheDocument();
    expect(screen.queryByText(councilBlock())).toBeNull();
  });

  it("leaves ordinary council-less code untouched", () => {
    render(<MarkdownContent content={"```json\n{\"type\":\"council\"}\n```\n"} streaming />);

    const code = screen.getByText('{"type":"council"}');
    expect(code.tagName).toBe("CODE");
    expect(code.className).not.toContain("language-council");
  });
});
