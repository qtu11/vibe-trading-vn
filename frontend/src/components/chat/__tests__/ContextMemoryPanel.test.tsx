import { fireEvent, render, screen } from "@testing-library/react";
import { ContextMemoryPanel } from "../ContextMemoryPanel";
import i18n from "@/i18n";

beforeAll(async () => { await i18n.changeLanguage("en"); });
afterEach(() => vi.unstubAllGlobals());

it("identifies a direct historical report replay as zero model calls", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ version: 1, session_id: "fixture", model_calls: 0,
    stored_messages: 4, preview: {}, last_run: { version: 1, source: "historical_forex_report", run_id: "fixture", initial_selection: { retrieved_messages: 1 } },
    last_run_usage: { totals: { input_tokens: 0, output_tokens: 0, calls: 0, cache_read_tokens: 0 } },
    memory: { available_entries: 0, error: null, entries: [], recall_preview: [] } }) }));
  render(<ContextMemoryPanel sessionId="fixture" />);
  fireEvent.click(screen.getByText("Context & memory"));
  expect(await screen.findByText(/This turn replayed a saved Forex report directly/)).toBeInTheDocument();
  expect(screen.queryByText(/older run has no recorded/)).not.toBeInTheDocument();
});

it("does not load diagnostics until opened, and never treats empty memory as saved facts", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ version: 1, session_id: "fixture", model_calls: 0,
    stored_messages: 20, preview: { recent_messages: 6, retrieved_messages: 2, omitted_messages: 12, history_chars: 11000, history_char_budget: 12000 },
    last_run: null, memory: { available_entries: 0, error: null, entries: [], recall_preview: [], automatic_fact_extraction: false } }) });
  vi.stubGlobal("fetch", fetch);
  render(<ContextMemoryPanel sessionId="fixture" />);
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Context & memory"));
  expect(await screen.findByText("No durable memories have been saved yet.")).toBeInTheDocument();
  expect(screen.getByText(/preview, not proof/)).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/sessions/fixture/context");
});

it("saves an explicit preference directly without invoking a research endpoint", async () => {
  const fixture = { version: 1, session_id: "fixture", model_calls: 0, stored_messages: 0, preview: {}, last_run: null,
    memory: { available_entries: 0, error: null, entries: [], recall_preview: [], automatic_fact_extraction: false } };
  const fetch = vi.fn().mockImplementation(async (_url, options) => ({ ok: true, json: async () => options?.method === "POST" ? { status: "saved", id: "fixture-memory", model_calls: 0 } : fixture }));
  vi.stubGlobal("fetch", fetch);
  render(<ContextMemoryPanel sessionId="fixture" />);
  fireEvent.click(screen.getByText("Context & memory"));
  await screen.findByText("Save a preference without a model call");
  fireEvent.click(screen.getByText("Save a preference without a model call"));
  fireEvent.change(screen.getByLabelText("Memory title"), { target: { value: "Candle preference" } });
  fireEvent.change(screen.getByLabelText("Preference or workflow"), { target: { value: "Explain closed candles." } });
  fireEvent.click(screen.getByRole("button", { name: "Save memory", exact: true }));
  expect(await screen.findByText("Memory saved for future turns. No model call was made.")).toBeInTheDocument();
  const writes = fetch.mock.calls.filter(([, options]) => options?.method === "POST");
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe("/sessions/fixture/memory");
  expect(JSON.parse(writes[0][1].body)).toEqual({ title: "Candle preference", content: "Explain closed candles.", memory_type: "user" });
});
