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
beforeEach(() => { vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url) => ({ ok: true, json: async () => String(url).startsWith("/settings/") ? context().model_context : context() }))); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("uses one estimated prompt rather than last-request or cumulative billed tokens", async () => {
  const data = context(); data.last_run_usage = { totals: { input_tokens: 9000000, output_tokens: 500000 } };
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => data } as Response);
  render(<ContextUsageIndicator sessionId="session-one" live={snapshot()} />);
  const trigger = screen.getByRole("button", { name: "Context approximately 25% used" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.pointerEnter(trigger);
  const tooltip = screen.getByRole("tooltip");
  expect(tooltip).toHaveTextContent("Context window");
  expect(tooltip).toHaveTextContent("25k / 100k tokens used");
  expect(tooltip).toHaveTextContent("Used 25% · 75% remaining");
  fireEvent.click(trigger);
  const popover = screen.getByRole("dialog", { name: "Context usage details" });
  expect(within(popover).getByText("25%")).toBeVisible();
  expect(within(popover).getByText("75% left")).toBeVisible();
  expect(within(popover).getByText("25k / 100k tokens used")).toBeVisible();
  expect(within(popover).getByText("Last provider input").parentElement).toHaveTextContent("80,000");
  expect(within(popover).getByText(/Last-request input and total billed tokens are separate/)).toBeVisible();
  expect(screen.queryByText("9,000,000")).not.toBeInTheDocument();
  expect(screen.queryByText("Saved messages")).not.toBeInTheDocument();
});

it("matches the Codex summary shape for a verified window", () => {
  render(<ContextUsageIndicator sessionId="session-one" live={snapshot({ model_window: 475000, estimated_next_request_tokens: 196000 })} />);
  fireEvent.click(screen.getByRole("button", { name: "Context approximately 41% used" }));
  expect(screen.getByText("196k / 475k tokens used")).toBeVisible();
  expect(screen.getByText("59% left")).toBeVisible();
});

it("renders the same card in Vietnamese", async () => {
  await i18n.changeLanguage("vi");
  render(<ContextUsageIndicator sessionId="session-one" live={snapshot()} />);
  fireEvent.click(screen.getByRole("button", { name: "Context đã dùng khoảng 25%" }));
  expect(screen.getByText("Cửa sổ ngữ cảnh")).toBeVisible();
  expect(screen.getByText("Đã sử dụng")).toBeVisible();
  expect(screen.getByText("Còn lại 75%")).toBeVisible();
  expect(screen.getByText("25k / 100k token được sử dụng")).toBeVisible();
  await i18n.changeLanguage("en");
});

it("discovers the selected model window before a chat session exists", async () => {
  vi.mocked(fetch).mockResolvedValue({ ok:true,json:async()=>({model:"model-exact",provider:"custom",window:64000,source:"provider:/models",confidence:"provider_reported", automatic_compaction: true, prompt_cost_cap: 60000}) } as Response);
  render(<ContextUsageIndicator sessionId={null} modelKey="custom:model-exact" />);
  await waitFor(() => expect(fetch).toHaveBeenCalledWith("/settings/llm/context",expect.anything()));
  fireEvent.click(screen.getByRole("button",{name:"Context usage unknown"}));
  expect(await screen.findByText("model-exact")).toBeVisible();
  expect(screen.getByText("64,000")).toBeVisible();
  expect(screen.getByRole("button",{name:"Refresh metadata"})).toBeEnabled();
  expect(screen.getByText("Automatic compaction enabled")).toBeVisible();
  expect(screen.getByText("60,000")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  expect(screen.getByText("Window confidence: provider_reported")).toBeVisible();
  expect(document.querySelector("circle[stroke-dasharray]")).toBeNull();
});

it("drops a live context percentage when the selected model changes", () => {
  const { rerender } = render(<ContextUsageIndicator sessionId="session-one" modelKey="fixture:fixture-model" live={snapshot()} />);
  expect(screen.getByRole("button", { name: "Context approximately 25% used" })).toBeVisible();
  rerender(<ContextUsageIndicator sessionId="session-one" modelKey="fixture:another-model" live={snapshot()} />);
  expect(screen.getByRole("button", { name: "Context usage unknown" })).toBeVisible();
});

it("discovers model metadata for existing chats before reading context and on refresh", async () => {
  const metadata = { ...context().model_context, source: "provider:/models", confidence: "provider_reported" };
  vi.mocked(fetch).mockImplementation(async (url) => ({ ok: true, json: async () => String(url).startsWith("/settings/") ? metadata : context() }) as Response);
  render(<ContextUsageIndicator sessionId="session-one" modelKey="fixture:fixture-model" />);
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toEqual(["/settings/llm/context", "/sessions/session-one/context"]);
  fireEvent.click(screen.getByRole("button", { name: "Context usage unknown" }));
  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  expect(screen.getByText("Window source: provider:/models")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Refresh metadata" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(4));
  expect(vi.mocked(fetch).mock.calls[2][0]).toBe("/settings/llm/context?refresh=true");
});

it("does not turn the previous run's context into the current occupancy", async () => {
  const data = context(); data.last_run = snapshot({ estimated_next_request_tokens: 99000 });
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => data } as Response);
  render(<ContextUsageIndicator sessionId="session-one" />);
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
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
  expect(screen.getByText("Compacting context…")).toBeVisible();
  const compacted = snapshot({ estimated_next_request_tokens: 10000, phase: "post_compaction" });
  compacted.compaction = { state: "completed", automatic: true, count: 1 };
  rerender(<ContextUsageIndicator sessionId="session-one" live={compacted} />);
  expect(screen.getByRole("button", { name: "Context approximately 10% used" })).toBeVisible();
  expect(screen.getByText("Context compacted")).toBeVisible();
});

it("dismisses by Escape, returns keyboard focus, and keeps diagnostics behind another action", () => {
  render(<ContextUsageIndicator sessionId="session-one" live={snapshot()} />);
  const trigger = screen.getByRole("button", { name: "Context approximately 25% used" });
  fireEvent.click(trigger);
  expect(screen.getByText("Context window")).toBeVisible();
  expect(screen.queryByText("History & long-term memory")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  expect(screen.getByText("History & long-term memory")).toBeVisible();
  expect(screen.queryByText("Persistent memory")).not.toBeInTheDocument();
  const cancellation = vi.fn(); document.addEventListener("keydown", cancellation);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
  expect(cancellation).not.toHaveBeenCalled(); document.removeEventListener("keydown", cancellation);
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
