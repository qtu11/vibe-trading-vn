import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { ForexTradeCards } from "../ForexTradeCards";
import { MessageBubble } from "../MessageBubble";
import { parseForexTradePlan, type ForexTradePlan } from "@/lib/forexTradePlan";

vi.mock("../RunCompleteCard", () => ({ RunCompleteCard: () => null }));

function fixture(): ForexTradePlan {
  const created = Date.now();
  return {
    version: 1, plan_id: "a".repeat(32), symbol: "XAUUSDm", currency: "USD", source: "mt5",
    environment: "demo", broker_server: "Fixture-Demo", binding_hash: "b".repeat(64), evidence_hash: "c".repeat(64),
    created_at: new Date(created).toISOString(), quote_at: new Date(created).toISOString(),
    expires_at: new Date(created + 60000).toISOString(), bid: "2000", ask: "2000.2", price_step: "0.05", minimum_stop_distance: "0.15",
    status: "ready", recommendation: "buy", reasons: [], workflow: "bounded_research_council_v1", trading_performed: false,
    scenarios: [
      { side: "buy", order_type: "market", entry: "2000.2", stop_loss: "1990", take_profit: "2020.6", reward_risk: "2", basis: "atr_structure_v1" },
      { side: "sell", order_type: "limit", entry: "2005", stop_loss: "2010", take_profit: "1995", reward_risk: "2", basis: "atr_structure_v1" },
    ],
    reports: (["technical", "macro", "bull", "bear", "risk", "manager"] as const).map(role => ({
      role, stance: "buy", entry_mode: "market", summary: "Evidence-based opinion", counterargument: "Wait if structure changes",
      evidence_refs: ["timeframes.1h"], veto: false, provider: "fixture", model: "fixture-model", elapsed_ms: 5,
    })), unique_models: 1,
  };
}

afterEach(() => vi.useRealTimers());

it("renders two accessible colored cards with MARKET/LIMIT and exact price strings", () => {
  const plan = fixture();
  expect(parseForexTradePlan(plan)).toEqual(plan);
  render(<ForexTradeCards plan={plan} />);
  const buy = screen.getByRole("article", { name: "BUY XAUUSDm" });
  const sell = screen.getByRole("article", { name: "SELL XAUUSDm" });
  expect(buy.className).toContain("emerald");
  expect(sell.className).toContain("red-");
  expect(within(buy).getByText(/MARKET/)).toBeInTheDocument();
  expect(within(sell).getByText(/LIMIT/)).toBeInTheDocument();
  for (const price of ["2000.2", "1990", "2020.6"]) expect(within(buy).getByText(price)).toBeInTheDocument();
  expect(screen.getAllByText(/Preferred scenario|Kịch bản ưu tiên/)).toHaveLength(1);
  expect(screen.getByText(/same model|cùng một model/)).toBeInTheDocument();
});

it("removes current recommendation automatically when the plan expires", () => {
  vi.useFakeTimers();
  const plan = fixture();
  render(<ForexTradeCards plan={plan} />);
  act(() => vi.advanceTimersByTime(61000));
  expect(screen.getByText(/EXPIRED · reanalyze|HẾT HẠN · cần phân tích lại/)).toBeInTheDocument();
  expect(screen.queryByText(/Preferred scenario|Kịch bản ưu tiên/)).not.toBeInTheDocument();
});

it("shows missing prices as unavailable without fabricating zero or a selected side", () => {
  const plan = fixture();
  plan.status = "blocked"; plan.recommendation = "wait"; plan.scenarios = []; plan.reports = []; plan.unique_models = 0;
  plan.reasons = ["DATA_OR_BROKER_CONSTRAINTS_INCOMPLETE"];
  expect(parseForexTradePlan(plan)).toEqual(plan);
  render(<ForexTradeCards plan={plan} />);
  expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(6);
  expect(screen.getByText(/WAIT · no entry|CHỜ · chưa khuyến nghị/)).toBeInTheDocument();
  expect(screen.queryByText("0")).not.toBeInTheDocument();
});

it("rejects forged ready states, invalid price geometry and malformed timestamps", () => {
  const plan = fixture();
  expect(parseForexTradePlan({ ...plan, reports: [] })).toBeUndefined();
  expect(parseForexTradePlan({ ...plan, expires_at: "invalid" })).toBeUndefined();
  expect(parseForexTradePlan({ ...plan, scenarios: [{ ...plan.scenarios[0], stop_loss: "2021" }] })).toBeUndefined();
  const veto = fixture(); veto.reports[4].veto = true;
  expect(parseForexTradePlan(veto)).toBeUndefined();
});

it("renders cards only from typed reply metadata, never a model-written JSON fence", () => {
  const plan = fixture();
  const { rerender } = render(<MessageBubble msg={{ id: "test", type: "answer", timestamp: Date.now(), content: `\`\`\`json\n${JSON.stringify(plan)}\n\`\`\`` }} />);
  expect(screen.queryByRole("article", { name: "BUY XAUUSDm" })).not.toBeInTheDocument();
  rerender(<MessageBubble msg={{ id: "test", type: "answer", timestamp: Date.now(), content: "Analysis complete", forexTradePlan: plan }} />);
  expect(screen.getByRole("article", { name: "BUY XAUUSDm" })).toBeInTheDocument();
});

it("shows an actual failed role without claiming a completed council or recommending entry", () => {
  const plan = fixture();
  plan.status = "blocked"; plan.recommendation = "wait"; plan.scenarios = [];
  plan.reports = plan.reports.slice(0, 3);
  plan.failures = [{ role: "bear", code: "INVALID_JSON" }];
  expect(parseForexTradePlan(plan)).toEqual(plan);
  render(<ForexTradeCards plan={plan} />);
  fireEvent.click(screen.getByText(/Analysis & debate|Phân tích & phản biện/));
  expect(screen.getByText(/3\/6/)).toBeInTheDocument();
  expect(screen.getByText(/Model did not return valid JSON|Model không trả JSON hợp lệ/)).toBeInTheDocument();
  expect(screen.queryByText(/Preferred scenario|Kịch bản ưu tiên/)).not.toBeInTheDocument();
});
