import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18n from "@/i18n";
import { ForexMarket } from "../ForexMarket";
import { defaultForexLimits, type ForexConnection } from "@/lib/forexApi";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/forexApi", async original => ({ ...await original<typeof import("@/lib/forexApi")>(), forexRequest: mock.request }));
vi.mock("../ForexLiveChart", () => ({ ForexLiveChart: ({ frame, onFrameChange }: { frame: string; onFrameChange: (f: string) => void }) => <button onClick={() => onFrameChange("1h")}>Chart {frame}</button> }));
vi.mock("@/components/chat/ForexTradeCards", () => ({ ForexTradeCards: ({ plan }: { plan: { connection_id: string } }) => <div data-testid="published-plan">{plan.connection_id}</div> }));
const connection = (id: string): ForexConnection => ({ id, label: id, connector: "mt5", environment: "demo", account_ref: "12345", execution_enabled: false,
  symbols: ["XAUUSDm"], terminal_path: "C:/Fixture/terminal64.exe", server: "Fixture-Demo", gateway_url: "", allowed_hosts: [], limits: defaultForexLimits, mandate_key: id, credential_ref: "", halted: false });
const plan = (id: string) => ({ version: 1, source: "mt5", plan_id: "a".repeat(32), symbol: "XAUUSDm", connection_id: id, currency: "USD", environment: "demo",
  broker_server: "Fixture-Demo", evidence_hash: "a".repeat(64), binding_hash: "b".repeat(64), status: "blocked", recommendation: "wait", reasons: [], scenarios: [], reports: [], unique_models: 0,
  bid: "100", ask: "100.1", created_at: new Date().toISOString(), quote_at: new Date().toISOString(), expires_at: new Date(Date.now() + 60000).toISOString(),
  workflow: "bounded_research_council_v1", trading_performed: false });
beforeAll(async () => { await i18n.changeLanguage("en"); });
beforeEach(() => mock.request.mockReset());

it("never invokes billable AI or order actions on mount; user analysis binds the selected frame/account", async () => {
  mock.request.mockResolvedValue(plan("first"));
  render(<ForexMarket connection={connection("first")} />);
  expect(mock.request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Chart 5m" }));
  fireEvent.click(screen.getByRole("button", { name: "AI: patterns & trend outlook" }));
  await screen.findByTestId("published-plan");
  expect(mock.request).toHaveBeenCalledTimes(1);
  expect(mock.request).toHaveBeenCalledWith("/api/forex/research-plan", expect.objectContaining({ connection_id: "first", forecast_timeframe: "1h", symbol: "XAUUSDm" }), "POST", 270000);
});

it("does not publish a late AI response into another account's chart", async () => {
  let resolve!: (v: unknown) => void;
  mock.request.mockReturnValueOnce(new Promise(r => { resolve = r; }));
  const { rerender } = render(<ForexMarket connection={connection("first")} />);
  fireEvent.click(screen.getByRole("button", { name: "AI: patterns & trend outlook" }));
  rerender(<ForexMarket connection={connection("second")} />);
  await act(async () => resolve(plan("first")));
  expect(screen.queryByTestId("published-plan")).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("button", { name: "AI: patterns & trend outlook" })).toBeEnabled());
});
