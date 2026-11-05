import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import i18n from "@/i18n";
import { MemoryRouter } from "react-router";
import { Forex } from "../Forex";
import { ForexConnectionForm } from "@/components/forex/ForexConnectionForm";
import { ForexOrders } from "@/components/forex/ForexOrders";
import { ForexAutomation } from "@/components/forex/ForexAutomation";
import { ForexAI } from "@/components/forex/ForexAI";
import { ForexEvidence } from "@/components/forex/ForexEvidence";
import { defaultForexLimits, type ForexConfig, type ForexConnection } from "@/lib/forexApi";

const apiMock = vi.hoisted(() => ({ forexRequest: vi.fn() }));
vi.mock("@/lib/forexApi", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/forexApi")>(), forexRequest: apiMock.forexRequest,
}));

function connection(overrides: Partial<ForexConnection> = {}): ForexConnection {
  return { id: "practice", label: "Practice", connector: "oanda", account_ref: "101-001", environment: "demo",
    execution_enabled: false, symbols: ["EUR_USD"], terminal_path: "", server: "", gateway_url: "", allowed_hosts: [],
    limits: { ...defaultForexLimits, max_quantity: "100" }, mandate_key: "forex-practice", credential_ref: "keyring://fixture",
    halted: false, ...overrides };
}

beforeAll(async () => { await i18n.changeLanguage("en"); });
beforeEach(() => { apiMock.forexRequest.mockReset(); });

it("shows missing history and macro observations without inventing zero values", () => {
  render(<ForexEvidence evidence={{ medium_term_price_context_ready: false,
    timeframes: { "1d": { status: "unavailable", history_sufficient: false } },
    macro: { real_yield_10y: { status: "unavailable", source_url: "https://fred.stlouisfed.org/series/DFII10" } },
  }} />);
  fireEvent.click(screen.getByText("Analysis data & sources"));
  const row = screen.getByRole("row", { name: /D1/ });
  expect(within(row).getAllByRole("cell")[1]).toHaveTextContent("—");
  expect(screen.getByText(/new AI entries are blocked/)).toBeVisible();
  const source = screen.getByRole("link", { name: /10Y real yield/ });
  expect(source.closest("li")).toHaveTextContent("Unavailable");
  expect(source.closest("li")).not.toHaveTextContent("0 %");
});

function aiFixture(allowed = false) {
  return { account_ref: "12345", environment: "demo", currency: "USD", equity: "2500", positions: [],
    trade_allowed: allowed, terminal_trade_allowed: allowed, external_api_disabled: !allowed, hedging: true };
}

it("shows external MT5 permission blocks while analysis remains available", async () => {
  apiMock.forexRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/ai")) return { analysis: null };
    if (path.endsWith("/account")) return { data: aiFixture() };
    if (path.endsWith("/ai/analyze")) return { status: "analyzed", decision: { action: "hold", confidence: 0.6, rationale: "Wait for a clearer signal" } };
    throw new Error("Unexpected path");
  });
  render(<ForexAI connection={connection({ connector: "mt5", execution_enabled: true })} runner={{ running: false, status: "stopped" }} reload={vi.fn()} onError={vi.fn()} />);
  expect(await screen.findByText(/Connected for data; MT5 execution/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Start automatic AI demo" })).toBeDisabled();
  expect(screen.getByText(/uncheck Disable automatic trading/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Analyze with AI" }));
  expect(await screen.findByText("Wait for a clearer signal")).toBeVisible();
  expect(screen.getByText(/Below the confidence threshold/)).toBeVisible();
  expect(apiMock.forexRequest.mock.calls.some(([path]) => path.endsWith("/submit") || path.endsWith("/ai/start"))).toBe(false);
});

it("starts the account-bound demo AI only on the explicit start action", async () => {
  apiMock.forexRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/ai")) return { analysis: null };
    if (path.endsWith("/account")) return { data: aiFixture(true) };
    if (path.endsWith("/ai/start")) return { running: true, mode: "ai" };
    throw new Error("Unexpected path");
  });
  render(<ForexAI connection={connection({ connector: "mt5", execution_enabled: true })} runner={{ running: false, status: "stopped" }} reload={vi.fn()} onError={vi.fn()} />);
  const start = screen.getByRole("button", { name: "Start automatic AI demo" });
  await waitFor(() => expect(start).toBeEnabled());
  expect(apiMock.forexRequest.mock.calls.some(([path]) => path.endsWith("/ai/start"))).toBe(false);
  fireEvent.click(start);
  await waitFor(() => expect(apiMock.forexRequest).toHaveBeenCalledWith("/api/forex/connections/practice/ai/start", expect.objectContaining({ symbol: "EUR_USD", timeframe: "5m", minimum_confidence: 0.75 })));
});

it("closes only an explicitly managed demo ticket through the durable intent endpoint", async () => {
  apiMock.forexRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/ai")) return { analysis: null };
    if (path.endsWith("/account")) return { data: { ...aiFixture(true), positions: [
      { ticket: 111, symbol: "EURUSDm", type: 0, volume: 0.01, managed: true, profit: 0 },
      { ticket: 222, symbol: "EURUSDm", type: 1, volume: 0.01, managed: false, profit: 0 },
    ] } };
    if (path.endsWith("/intents")) return { id: "fx_close" };
    if (path.endsWith("/submit")) return { state: "filled" };
    throw new Error("Unexpected path");
  });
  render(<ForexAI connection={connection({ connector: "mt5", execution_enabled: true })} runner={{ running: false, status: "stopped" }} reload={vi.fn()} onError={vi.fn()} />);
  const close = await screen.findByRole("button", { name: "Close managed position" });
  expect(screen.getAllByRole("button", { name: "Close managed position" })).toHaveLength(1);
  fireEvent.click(close);
  await waitFor(() => expect(apiMock.forexRequest).toHaveBeenCalledWith("/api/forex/connections/practice/intents", expect.objectContaining({ action: "close", position_ticket: "111", side: "sell", quantity: "0.01" })));
  await waitFor(() => expect(apiMock.forexRequest).toHaveBeenCalledWith("/api/forex/connections/practice/intents/fx_close/submit", {}));
});

it("saves explicit native symbols while execution stays read-only by default", async () => {
  const user = userEvent.setup(); const saved = vi.fn(async (_config: ForexConfig) => {});
  render(<ForexConnectionForm onSave={saved} />);
  fireEvent.change(screen.getByLabelText("Platform"), { target: { value: "oanda" } });
  fireEvent.change(screen.getByLabelText("Account ID / login"), { target: { value: "101-001" } });
  const symbols = screen.getByLabelText(/Allowed native symbols/);
  await user.type(symbols, "EUR_USD, GBP_USD");
  expect(symbols).toHaveValue("EUR_USD, GBP_USD");
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  await user.click(screen.getByRole("button", { name: "Save connection" }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(saved.mock.calls[0][0]).toMatchObject({ symbols: ["EUR_USD", "GBP_USD"], execution_enabled: false });
});

it("allows a read-only risk preview without enabling order submission", async () => {
  apiMock.forexRequest.mockResolvedValue({ assessment: { notional_usd: "108.01", stop_risk_usd: "3.01", estimated_margin: "4" } });
  render(<ForexOrders connection={connection()} intents={[]} reload={vi.fn()} onError={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Stop loss"), { target: { value: "1.05" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview risk" }));
  expect(await screen.findByText("108.01")).toBeVisible();
  expect(screen.getByRole("button", { name: "Submit protected order" })).toBeDisabled();
  expect(apiMock.forexRequest).toHaveBeenCalledOnce();
  expect(apiMock.forexRequest.mock.calls[0][0]).toContain("/preview");
});

it("requires live acknowledgement and never retries a timed-out submission", async () => {
  const reload = vi.fn(async () => {}); const onError = vi.fn();
  apiMock.forexRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/preview")) return { assessment: { notional_usd: "108.01" } };
    if (path.endsWith("/intents")) return { id: "fx_fixture" };
    if (path.endsWith("/submit")) throw new Error("Request timed out; reconcile the intent");
    throw new Error("Unexpected path");
  });
  render(<ForexOrders connection={connection({ environment: "live", execution_enabled: true })} intents={[]} reload={reload} onError={onError} />);
  fireEvent.change(screen.getByLabelText("Stop loss"), { target: { value: "1.05" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview risk" }));
  await screen.findByText("108.01");
  const submit = screen.getByRole("button", { name: "Submit protected order" });
  expect(submit).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(submit);
  await waitFor(() => expect(onError).toHaveBeenLastCalledWith(expect.stringContaining("timed out")));
  expect(apiMock.forexRequest.mock.calls.filter(([path]) => path.endsWith("/submit"))).toHaveLength(1);
  expect(reload).toHaveBeenCalledOnce();
  expect(submit).toBeDisabled();
});

it("discards the previous account's late journal response after selection changes", async () => {
  let resolveOld: (value: unknown) => void = () => {};
  const pending = new Promise(resolve => { resolveOld = resolve; });
  const first = connection(); const second = connection({ id: "second", label: "Second", account_ref: "101-002" });
  const intent = (symbol: string) => ({ id: "fx_" + symbol, state: "filled", payload: { symbol, side: "buy", quantity: "1" }, result: {} });
  apiMock.forexRequest.mockImplementation(async (path: string) => {
    if (path === "/api/forex/connections") return { connections: [first, second] };
    if (path.endsWith("/practice/intents")) return pending;
    if (path.endsWith("/second/intents")) return { intents: [intent("SECOND_SYMBOL")] };
    if (path.endsWith("/runner")) return { running: false, status: "stopped" };
    throw new Error("Unexpected path");
  });
  render(<MemoryRouter><Forex /></MemoryRouter>);
  await waitFor(() => expect(apiMock.forexRequest.mock.calls.some(([path]) => path.endsWith("/practice/intents"))).toBe(true));
  fireEvent.change(screen.getByLabelText("Selected account"), { target: { value: "second" } });
  expect(await screen.findByText("SECOND_SYMBOL")).toBeVisible();
  await act(async () => resolveOld({ intents: [intent("OLD_ACCOUNT_SYMBOL")] }));
  expect(screen.queryByText("OLD_ACCOUNT_SYMBOL")).not.toBeInTheDocument();
  expect(screen.getByText("SECOND_SYMBOL")).toBeVisible();
});

it("renders the backend live mandate shape and commits only after account consent", async () => {
  apiMock.forexRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/mandate-proposal")) return { proposal_id: "fixture-proposal", account_ref: "101-001", profiles: [{
      ordinal: 1, max_order_usd: 1000, max_total_exposure_usd: 3000, daily_trade_cap: 5, leverage: 2, instruments: ["forex", "cfd"],
    }] };
    if (path === "/mandate/commit") return { expires_at: "2026-11-04T00:00:00Z" };
    throw new Error("Unexpected path");
  });
  render(<ForexAutomation connection={connection({ environment: "live" })} status={{ running: false, status: "stopped" }} reload={vi.fn(async () => {})} onError={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Prepare live mandate" }));
  const choose = await screen.findByRole("button", { name: /#1: \$1000/ });
  expect(choose).toHaveTextContent("forex, cfd");
  expect(choose).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(choose);
  await waitFor(() => expect(apiMock.forexRequest).toHaveBeenCalledWith("/mandate/commit", expect.objectContaining({
    broker: "forex-practice", account_ref: "101-001", consent_ack: true, proposal_id: "fixture-proposal", selected_ordinal: 1, lifetime_days: 1,
  })));
});
