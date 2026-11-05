import { render, screen } from "@testing-library/react";
import { ForexTrendForecast } from "../ForexTrendForecast";
import type { ForexTradePlan } from "@/lib/forexTradePlan";

it("shows conditional direction separately from the entry recommendation", () => {
  const plan = { created_at: "2026-11-03T03:00:00Z", recommendation: "wait", evidence: { timeframes: { "1h": {
    price_action: { status: "ok", as_of: "2026-11-03T00:00:00Z" },
  } } }, reports: [{ role: "manager", forecast: {
    direction: "down", timeframe: "1h", horizon_bars: 6, rationale: "Closed swings remain bearish.", invalidation: "A close above resistance invalidates the view.",
  } }] } as unknown as ForexTradePlan;
  render(<ForexTrendForecast plan={plan} />);
  expect(screen.getByText(/Down.*H1.*6|Giảm.*H1.*6/)).toBeInTheDocument();
  expect(screen.getByText(/above resistance/)).toBeInTheDocument();
  expect(screen.getByText(/WAIT remains valid|CHỜ vẫn có hiệu lực/)).toBeInTheDocument();
  expect(screen.getByText(/Last closed input candle|Nến đóng cuối trong dữ liệu/)).toHaveTextContent("2026-11-03 00:00:00Z");
  expect(screen.getByText(/Snapshot/)).toHaveTextContent("2026-11-03 03:00:00Z");
});
