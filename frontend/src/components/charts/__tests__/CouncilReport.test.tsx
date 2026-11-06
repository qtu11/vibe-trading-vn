import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CouncilReport, parseCouncilBlock } from "../CouncilReport";

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

function council(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    type: "council",
    version: 1,
    symbol: "FPT.VN",
    generated_at: "2026-11-06T10:00:00+00:00",
    snapshot: {
      symbol: "FPT.VN",
      source: "yahoo",
      currency: "VND",
      adjustment: "split_dividend",
      as_of: "2026-11-05",
      bars: 36,
      last_close: 67000,
      window_low: 62400,
      window_low_date: "2026-09-20",
      window_high: 67900,
      window_high_date: "2026-10-31",
    },
    chart: {
      type: "candlestick",
      symbol: "FPT.VN",
      currency: "VND",
      source: "yahoo",
      as_of: "2026-11-05",
      bars: [
        { t: "2026-11-04", o: 66500, h: 67200, l: 66000, c: 67000, v: 1_000_000 },
        { t: "2026-11-05", o: 67000, h: 67600, l: 66800, c: 67400, v: 900_000 },
      ],
    },
    verdict: {
      stance: "buy",
      stance_label: "MUA",
      horizon: "3-6 tháng",
      confidence_pct: 68,
      fair_value: { low: 72000, high: 78000 },
      entry_zone: { low: 62000, high: 64000 },
      stop: 59500,
      position_cap_pct: 5,
      catalysts: ["Ký thêm hợp đồng xuất khẩu phần mềm"],
      risks: ["Tăng trưởng chậm lại ở mảng nước ngoài"],
      invalidation: "Đóng cửa dưới 59,5 trong 3 phiên",
      verification: "reported_by_council",
      sources: [
        {
          ref: "S1",
          title: "Báo cáo thường niên FPT 2025",
          publisher: "FPT",
          url: "https://fpt.com.vn/bao-cao-thuong-nien",
          published_at: "2026-03-30",
          tier: "tier 1",
          verification: "reported_by_council",
        },
      ],
    },
    evaluation: {
      price_scale: 1000,
      price_scale_note: "verdict prices were quoted at 10^3 of the observed unit",
      entry_mid: 63000,
      risk_per_share: 3500,
      risk_reward: 2.57,
      stop_distance_pct: 5.56,
      sizing: {
        available: true,
        currency: "VND",
        lot_size: 100,
        risk_1pct: { risk_pct: 1, shares: 2800 },
        risk_2pct: { risk_pct: 2, shares: 5700 },
        position_cap: { cap_pct: 5, shares: 700 },
        binding: "position_cap",
      },
    },
    issues: [],
    actionable: true,
    trade_actionable: true,
    blocked_reason: null,
    debate: [
      {
        agent_id: "bull_advocate",
        role: "Bên mua (Bull)",
        status: "completed",
        summary: "Tăng trưởng doanh thu phần mềm và hợp đồng mới hỗ trợ luận điểm mua.",
      },
      {
        agent_id: "bear_advocate",
        role: "Bên bán (Bear)",
        status: "completed",
        summary: "Định giá đã phản ánh nhiều kỳ vọng và rủi ro tập trung khách hàng.",
      },
      {
        agent_id: "risk_officer",
        role: "Quản trị rủi ro",
        status: "completed",
        summary: "Giới hạn vị thế 5% NAV, stop 59,5.",
      },
    ],
    pm_report: "Tóm tắt quyết định của PM.",
    sources: [
      {
        ref: "S1",
        title: "Báo cáo thường niên FPT 2025",
        url: "https://fpt.com.vn/bao-cao-thuong-nien",
        publisher: "FPT",
        published_at: "2026-03-30",
        verification: "reported_by_council",
      },
    ],
    disclaimer: "Khuyến nghị tham khảo, không phải cam kết lợi nhuận.",
    ...overrides,
  };
}

describe("parseCouncilBlock", () => {
  it("parses the verdict, evaluation and debate a reader needs", () => {
    const parsed = parseCouncilBlock(JSON.stringify(council()));

    expect(parsed).not.toBeNull();
    expect(parsed?.symbol).toBe("FPT.VN");
    expect(parsed?.verdict?.stance_label).toBe("MUA");
    expect(parsed?.verdict?.entry_zone).toEqual({ low: 62000, high: 64000 });
    expect(parsed?.evaluation?.risk_reward).toBeCloseTo(2.57);
    expect(parsed?.evaluation?.sizing?.binding).toBe("position_cap");
    expect(parsed?.debate).toHaveLength(3);
    expect(parsed?.sources?.[0].verification).toBe("reported_by_council");
  });

  it("accepts a verdict-less block for the not-actionable case", () => {
    const parsed = parseCouncilBlock(
      JSON.stringify(council({ verdict: null, actionable: false, sources: [] })),
    );

    expect(parsed).not.toBeNull();
    expect(parsed?.verdict).toBeNull();
    expect(parsed?.actionable).toBe(false);
  });

  it("rejects malformed JSON and the wrong block type", () => {
    expect(parseCouncilBlock("```council")).toBeNull();
    expect(parseCouncilBlock("null")).toBeNull();
    expect(parseCouncilBlock(JSON.stringify({ type: "chart", symbol: "FPT.VN" }))).toBeNull();
    expect(parseCouncilBlock(JSON.stringify(council({ symbol: "" })) )).toBeNull();
    expect(parseCouncilBlock(JSON.stringify(council({ verdict: "MUA" })) )).toBeNull();
  });

  it("drops unsafe links instead of rendering them", () => {
    const parsed = parseCouncilBlock(
      JSON.stringify(
        council({
          sources: [
            {
              ref: "S1",
              title: "unsafe",
              url: "javascript:alert(1)",
              verification: "reported_by_council",
            },
          ],
        }),
      ),
    );

    expect(parsed?.sources?.[0].url).toBeNull();
  });
});

describe("CouncilReport", () => {
  it("renders the verdict, both debate columns and the labelled sources", () => {
    render(<CouncilReport code={JSON.stringify(council())} />);

    expect(screen.getByText("MUA")).toBeInTheDocument();
    expect(screen.getByText("3-6 tháng")).toBeInTheDocument();
    expect(screen.getByText(/Tăng trưởng doanh thu phần mềm/)).toBeInTheDocument();
    expect(screen.getByText(/Định giá đã phản ánh/)).toBeInTheDocument();
    expect(screen.getByText("Báo cáo thường niên FPT 2025")).toBeInTheDocument();
    expect(screen.getByText("reported_by_council")).toBeInTheDocument();
    expect(screen.getByText(/Khuyến nghị tham khảo/)).toBeInTheDocument();
  });

  it("renders the attached deterministic chart", () => {
    render(<CouncilReport code={JSON.stringify(council())} />);

    expect(screen.getByRole("button", { name: /Indicators/ })).toBeInTheDocument();
  });

  it("shows why a blocked verdict is not advice", () => {
    render(
      <CouncilReport
        code={JSON.stringify(
          council({
            actionable: false,
            trade_actionable: false,
            blocked_reason: "sources_missing",
            verdict: {
              ...(council().verdict as Record<string, unknown>),
              sources: [],
            },
            sources: [],
          }),
        )}
      />,
    );

    expect(screen.getByText(/not actionable/)).toBeInTheDocument();
    expect(screen.getByText(/Blocked: sources_missing/)).toBeInTheDocument();
    expect(screen.getByText(/No source was named/)).toBeInTheDocument();
  });

  it("falls back to a code block when the fence is not a council block", () => {
    render(<CouncilReport code={"not json at all"} />);

    expect(screen.getByText("not json at all")).toBeInTheDocument();
    expect(document.querySelector("figcaption")).toBeNull();
  });
});
