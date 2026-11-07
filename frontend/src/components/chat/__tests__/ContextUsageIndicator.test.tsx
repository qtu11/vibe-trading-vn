import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import i18n from "@/i18n";
import type { ContextSnapshot, ContextView } from "../ContextMemoryPanel";
import { ContextUsageIndicator } from "../ContextUsageIndicator";

const snapshot = (overrides: Partial<NonNullable<ContextSnapshot["current_prompt"]>> = {}): ContextSnapshot => ({
  version: 1, source: "agent_loop", session_id: "session-one", run_id: "run-one",
  current_prompt: { model: "fixture-model", provider: "fixture", model_window: 100000,
    window_source: "catalog:fixture", window_confidence: "catalog", estimated_next_request_tokens: 25000,
    last_reported_input_tokens: 80000, phase: "pre_request", compact_at: 70000, prompt_cost_cap: 80000,
    observed_at: "2026-11-07T00:00:00Z", ...overrides },
  compaction: { state: "idle", automatic: true, count: 0 },
});
const context = (sessionId = "session-one"): ContextView => ({
  version: 1, session_id: sessionId, model_calls: 0, stored_messages: 12, preview: {}, last_run: null,
  model_context: { model: "fixture-model", provider: "fixture", window: 100000, source: "catalog:fixture", confidence: "catalog" },
  memory: { available_entries: 0, error: null, entries: [], recall_preview: [], automatic_fact_extraction: false },
});
beforeAll(async () => { await i18n.changeLanguage("en"); });
beforeEach(() => { vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => context() })); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("uses one estimated prompt rather than last-request or cumulative billed tokens", async () => {
  const data = context(); data.last_run_usage = { totals: { input_tokens: 9000000, output_tokens: 500000 } };
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => data } as Response);
  render(<ContextUsageIndicator sessionId="session-one" live={snapshot()} />);
  const trigger = screen.getByRole("button", { name: "Context approximately 25% used" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.pointerEnter(trigger);
  expect(screen.getByRole("tooltip")).toHaveTextContent("Estimated prompt: 25,000 · Remaining: 75,000");
  fireEvent.click(trigger);
  const popover = screen.getByRole("dialog", { name: "Context usage details" });
  expect(within(popover).getByText("Last provider input").parentElement).toHaveTextContent("80,000");
  expect(within(popover).getByText(/Last-request input and total billed tokens are separate/)).toBeVisible();
  expect(screen.queryByText("9,000,000")).not.toBeInTheDocument();
  expect(screen.queryByText("Saved messages")).not.toBeInTheDocument();
});

it("does not turn the previous run's context into the current occupancy", async () => {
  const data = context(); data.last_run = snapshot({ estimated_next_request_tokens: 99000 });
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => data } as Response);
  render(<ContextUsageIndicator sessionId="session-one" />);
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole("button", { name: "Context usage unknown" }));
  expect(await screen.findByText(/prior run's context is available in diagnostics/)).toBeVisible();
  expect(screen.queryByText("~99%")).not.toBeInTheDocument();
});

it.each([
  { window_source: "default", window_confidence: "fallback" },
  { window_source: "catalog:fixture", window_confidence: "unknown" },
  { window_source: undefined, window_confidence: undefined },
])("keeps unknown/fallback windows neutral instead of inferring a percentage: %j", async (metadata) => {
  const { container } = render(<ContextUsageIndicator sessionId="session-one" live={snapshot(metadata)} />);
  fireEvent.click(screen.getByRole("button", { name: "Context usage unknown" }));
  expect(screen.getByText(/conservative fallback budget/)).toBeVisible();
  expect(container.querySelector("circle[stroke-dasharray]")).toBeNull();
});

it("renders a genuine zero estimate but not invalid negative input", () => {
  const { rerender } = render(<ContextUsageIndicator sessionId="session-one" live={snapshot({ estimated_next_request_tokens: 0 })} />);
  expect(screen.getByRole("button", { name: "Context approximately 0% used" })).toBeVisible();
  rerender(<ContextUsageIndicator sessionId="session-one" live={snapshot({ estimated_next_request_tokens: -1 })} />);
  expect(screen.getByRole("button", { name: "Context usage unknown" })).toBeVisible();
});

it("updates from compaction snapshots without claiming a running summary already freed tokens", () => {
  const live = snapshot({ estimated_next_request_tokens: 80000 });
  live.compaction = { state: "running", automatic: true, count: 0 };
  const { rerender } = render(<ContextUsageIndicator sessionId="session-one" live={live} />);
  fireEvent.click(screen.getByRole("button", { name: "Context approximately 80% used" }));
  expect(screen.getByText("Compacting context…", { selector: "p" })).toBeVisible();
  const compacted = snapshot({ estimated_next_request_tokens: 10000, phase: "post_compaction" });
  compacted.compaction = { state: "completed", automatic: true, count: 1 };
  rerender(<ContextUsageIndicator sessionId="session-one" live={compacted} />);
  expect(screen.getByRole("button", { name: "Context approximately 10% used" })).toBeVisible();
  expect(screen.getByText("Context compacted", { selector: "p" })).toBeVisible();
});

it("dismisses by Escape, returns keyboard focus, and keeps diagnostics behind another action", () => {
  render(<ContextUsageIndicator sessionId="session-one" live={snapshot()} />);
  const trigger = screen.getByRole("button", { name: "Context approximately 25% used" });
  fireEvent.click(trigger);
  expect(screen.getByText("History & long-term memory")).toBeVisible();
  expect(screen.queryByText("Persistent memory")).not.toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

it("aborts metadata reads and ignores stale session results", async () => {
  let resolve!: (value: Response) => void;
  vi.mocked(fetch).mockImplementationOnce(() => new Promise((done) => { resolve = done; }))
    .mockResolvedValue({ ok: true, json: async () => context("session-two") } as Response);
  const { rerender } = render(<ContextUsageIndicator sessionId="session-one" />);
  const signal = vi.mocked(fetch).mock.calls[0][1]!.signal!;
  rerender(<ContextUsageIndicator sessionId="session-two" live={snapshot()} />);
  expect(signal.aborted).toBe(true);
  await act(async () => resolve({ ok: true, json: async () => context() } as Response));
  expect(screen.getByRole("button", { name: "Context usage unknown" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Context usage unknown" }));
  expect(screen.queryByText("~25%")).not.toBeInTheDocument();
});

it("reads authenticated metadata and exposes errors only in the opened popover", async () => {
  vi.stubGlobal("localStorage", { getItem: () => "context-key", setItem: vi.fn(), removeItem: vi.fn() });
  vi.mocked(fetch).mockResolvedValue({ ok: false } as Response);
  render(<ContextUsageIndicator sessionId="session-one" />);
  await waitFor(() => expect(fetch).toHaveBeenCalledWith("/sessions/session-one/context", expect.objectContaining({ headers: { Authorization: "Bearer context-key" } })));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Context usage unknown" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Cannot read context status");
});
