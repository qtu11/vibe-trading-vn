import { act, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { Agent } from "../Agent";
import { useAgentStore } from "@/stores/agent";

const apiMock = vi.hoisted(() => ({ getGoal: vi.fn(), getLLMSettings: vi.fn(), getRunPreview: vi.fn(), getSessionMessages: vi.fn(), sseUrl: vi.fn((sid: string) => `/sessions/${sid}/events`) }));
const sseMock = vi.hoisted(() => ({ connect: vi.fn(), disconnect: vi.fn(), onStatusChange: vi.fn() }));
vi.mock("@/lib/api", async () => ({ ...await vi.importActual<typeof import("@/lib/api")>("@/lib/api"), api: apiMock }));
vi.mock("@/hooks/useSSE", () => ({ useSSE: () => sseMock }));
const handlers = () => sseMock.connect.mock.calls.at(-1)![1] as Record<string, (data: Record<string, unknown>) => void>;
const snapshot = (overrides: Record<string, unknown> = {}) => ({
  version: 1, source: "agent_loop", session_id: "session-one", attempt_id: "attempt-one", run_id: "run-one",
  current_prompt: { model: "fixture", model_window: 100000, window_source: "catalog:fixture", window_confidence: "catalog", estimated_next_request_tokens: 25000, last_reported_input_tokens: 80000, phase: "pre_request" },
  ...overrides,
});
beforeEach(() => {
  useAgentStore.getState().reset(); sseMock.connect.mockClear();
  apiMock.getGoal.mockResolvedValue(null); apiMock.getSessionMessages.mockResolvedValue([]);
  apiMock.getRunPreview.mockResolvedValue({ metrics: null, equity_curve: [], report_worthy: false });
  apiMock.getLLMSettings.mockResolvedValue({ provider: "fixture", model_name: "fixture", api_key_configured: true, api_key_required: true, timeout_seconds: 120, max_retries: 2, sse_timeout_seconds: 90, providers: [] });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ version: 1, session_id: "session-one", last_run: null, model_context: { model: "fixture", window: 100000, source: "catalog:fixture", confidence: "catalog" } }) }));
  Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: vi.fn() });
});
afterEach(() => vi.unstubAllGlobals());
async function start() {
  render(<RouterProvider router={createMemoryRouter([{ path: "/", element: <Agent /> }], { initialEntries: ["/?session=session-one"] })} />);
  await waitFor(() => expect(sseMock.connect).toHaveBeenCalled());
  act(() => handlers()["attempt.started"]({ attempt_id: "attempt-one", run_id: "run-one" }));
}

it("places the compact context control below the composer and updates only from context telemetry", async () => {
  await start();
  const control = screen.getByRole("button", { name: "Context usage unknown" });
  expect(control.closest("[data-agent-composer]")).not.toBeNull();
  expect(screen.queryByText("Context & memory")).not.toBeInTheDocument();
  act(() => handlers().llm_usage({ attempt_id: "attempt-one", iter: 1, input_tokens: 900000, output_tokens: 12000, total_tokens: 912000 }));
  expect(screen.getByRole("button", { name: "Context usage unknown" })).toBeVisible();
  act(() => handlers().context_snapshot(snapshot()));
  expect(screen.getByRole("button", { name: "Context approximately 25% used" })).toBeVisible();
});

it("rejects context from another session, attempt, or run", async () => {
  await start();
  for (const wrong of [{ session_id: "another-session" }, { attempt_id: "another-attempt" }, { run_id: "another-run" }]) {
    act(() => handlers().context_snapshot(snapshot(wrong)));
    expect(screen.getByRole("button", { name: "Context usage unknown" })).toBeVisible();
  }
  act(() => handlers().context_snapshot(snapshot()));
  expect(screen.getByRole("button", { name: "Context approximately 25% used" })).toBeVisible();
});

it("clears the prior estimate on a new attempt before new telemetry arrives", async () => {
  await start();
  act(() => handlers().context_snapshot(snapshot()));
  expect(screen.getByRole("button", { name: "Context approximately 25% used" })).toBeVisible();
  act(() => handlers()["attempt.started"]({ attempt_id: "attempt-two", run_id: "run-two" }));
  expect(screen.getByRole("button", { name: "Context usage unknown" })).toBeVisible();
  act(() => handlers().context_snapshot(snapshot()));
  expect(screen.getByRole("button", { name: "Context usage unknown" })).toBeVisible();
});
