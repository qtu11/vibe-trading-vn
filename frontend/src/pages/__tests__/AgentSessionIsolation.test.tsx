import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { Agent } from "../Agent";
import { useAgentStore } from "@/stores/agent";

const apiMock = vi.hoisted(() => ({
  getGoal: vi.fn(), getLLMSettings: vi.fn(), getRunPreview: vi.fn(),
  getSessionMessages: vi.fn(), autoTitleSession: vi.fn(),
  sendMessage: vi.fn(), cancelSession: vi.fn(), getSwarmRun: vi.fn(),
  createGoal: vi.fn(), createSession: vi.fn(), updateGoalStatus: vi.fn(),
  sseUrl: vi.fn((sid: string) => `/sessions/${sid}/events`),
}));
const sseMock = vi.hoisted(() => ({ connect: vi.fn(), disconnect: vi.fn(), onStatusChange: vi.fn() }));
vi.mock("@/lib/api", async () => ({ ...await vi.importActual<typeof import("@/lib/api")>("@/lib/api"), api: apiMock }));
vi.mock("@/hooks/useSSE", () => ({ useSSE: () => sseMock }));
vi.mock("@/components/chat/RunCompleteCard", () => ({ RunCompleteCard: () => <div>Run card</div> }));

type Handlers = Record<string, (data: Record<string, unknown>) => void | Promise<void>>;
function handlers(): Handlers { return sseMock.connect.mock.calls.at(-1)![1]; }
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
function storedReply(attemptId: string, metadata: Record<string, unknown> = {}) {
  return { message_id: `reply-${attemptId}`, role: "assistant", content: "Stored answer", linked_attempt_id: attemptId, created_at: "2026-11-08T00:00:00Z", metadata, tool_trail: [] };
}
async function mount(sid: string) {
  const router = createMemoryRouter([{ path: "/", element: <Agent /> }], { initialEntries: [`/?session=${sid}`] });
  render(<RouterProvider router={router} />);
  await waitFor(() => expect(useAgentStore.getState().sessionLoading).toBe(false));
  return router;
}
function submit(prompt = "Research this company") {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: prompt } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
}
function startNextAttempt(id: string) {
  act(() => {
    const store = useAgentStore.getState();
    store.startActivity(id);
    store.setStatus("streaming");
    store.appendDelta("Next attempt evidence");
  });
}
function goal(sid: string) {
  return { goal: { goal_id: `goal-${sid}`, session_id: sid, objective: `Study ${sid}`, ui_summary: `Study ${sid}`, status: "active" }, criteria: [], evidence: [], evidence_count: 0, claims: [] };
}
function enableGoal() {
  fireEvent.click(screen.getByRole("button", { name: "More options" }));
  fireEvent.click(screen.getByRole("menuitem", { name: /Research Goal/ }));
}

describe("Agent async session and attempt isolation", () => {
  beforeEach(() => {
    useAgentStore.getState().reset();
    vi.clearAllMocks();
    apiMock.sendMessage.mockReset();
    apiMock.createGoal.mockReset();
    apiMock.createSession.mockReset();
    apiMock.getGoal.mockResolvedValue(null);
    apiMock.getLLMSettings.mockResolvedValue({ provider: "custom", model_name: "fixture-model", providers: [], reasoning_effort: "", sse_timeout_seconds: 90 });
    apiMock.getRunPreview.mockResolvedValue({ report_worthy: false, metrics: null, equity_curve: [] });
    apiMock.autoTitleSession.mockResolvedValue({});
    const seen = new Set<string>();
    apiMock.getSessionMessages.mockImplementation((sid: string) => {
      if (seen.has(sid)) return new Promise(() => {});
      seen.add(sid);
      return Promise.resolve([]);
    });
    Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: vi.fn() });
  });

  it("does not append a completed run's late equity preview to another chat", async () => {
    const preview = deferred<{ report_worthy: boolean; metrics: { final_value: number }; equity_curve: [] }>();
    apiMock.getRunPreview.mockReturnValue(preview.promise);
    const router = await mount("preview-a");
    let completion!: Promise<void>;
    act(() => { completion = handlers()["attempt.completed"]({ attempt_id: "attempt-a", summary: "A answer", run_dir: "/runs/run-a" }) as Promise<void>; });
    await waitFor(() => expect(apiMock.getRunPreview).toHaveBeenCalledWith("run-a"));
    await act(async () => { await router.navigate("/?session=preview-b"); });
    await act(async () => { preview.resolve({ report_worthy: true, metrics: { final_value: 110 }, equity_curve: [] }); await completion; });
    expect(useAgentStore.getState().sessionId).toBe("preview-b");
    expect(useAgentStore.getState().messages.some((message) => message.runId === "run-a")).toBe(false);
  });

  it("does not bind another chat's pending attempt to a late send acknowledgement", async () => {
    const sent = deferred<{ attempt_id: string }>();
    apiMock.sendMessage.mockReturnValue(sent.promise);
    const router = await mount("send-a");
    submit();
    await waitFor(() => expect(apiMock.sendMessage).toHaveBeenCalled());
    await act(async () => { await router.navigate("/?session=send-b"); });
    startNextAttempt("pending-b");
    await act(async () => { sent.resolve({ attempt_id: "attempt-a" }); await Promise.resolve(); });
    expect(useAgentStore.getState().activity?.attemptId).toBe("pending-b");
    expect(useAgentStore.getState().streamingText).toBe("Next attempt evidence");
  });

  it("does not fail another chat's active turn when an earlier send rejects", async () => {
    const sent = deferred<{ attempt_id: string }>();
    apiMock.sendMessage.mockReturnValue(sent.promise);
    const router = await mount("reject-a");
    submit();
    await waitFor(() => expect(apiMock.sendMessage).toHaveBeenCalled());
    await act(async () => { await router.navigate("/?session=reject-b"); });
    startNextAttempt("pending-b");
    await act(async () => { sent.reject(new Error("A send rejected")); await Promise.resolve(); });
    expect(useAgentStore.getState().activity?.attemptId).toBe("pending-b");
    expect(useAgentStore.getState().status).toBe("streaming");
    expect(useAgentStore.getState().messages.some((message) => message.type === "error")).toBe(false);
  });

  it("does not stop another chat's active turn when a previous cancel resolves", async () => {
    const cancelled = deferred<unknown>();
    apiMock.cancelSession.mockReturnValue(cancelled.promise);
    const router = await mount("cancel-a");
    act(() => { handlers()["attempt.started"]({ attempt_id: "attempt-a" }); });
    fireEvent.click(screen.getByRole("button", { name: "Stop generation" }));
    await waitFor(() => expect(apiMock.cancelSession).toHaveBeenCalledWith("cancel-a"));
    await act(async () => { await router.navigate("/?session=cancel-b"); });
    startNextAttempt("pending-b");
    await act(async () => { cancelled.resolve({}); await Promise.resolve(); });
    expect(useAgentStore.getState().activity?.attemptId).toBe("pending-b");
    expect(useAgentStore.getState().status).toBe("streaming");
    expect(useAgentStore.getState().streamingText).toBe("Next attempt evidence");
  });

  it("does not clear a newer attempt when an earlier completion poll resolves", async () => {
    const poll = deferred<ReturnType<typeof storedReply>[]>();
    apiMock.getSessionMessages.mockResolvedValueOnce([]).mockReturnValue(poll.promise);
    apiMock.sendMessage.mockResolvedValue({ attempt_id: "attempt-a" });
    await mount("poll-a");
    submit();
    await waitFor(() => expect(apiMock.getSessionMessages).toHaveBeenCalledTimes(2));
    await act(async () => { await handlers()["attempt.completed"]({ attempt_id: "attempt-a", summary: "First complete" }); });
    startNextAttempt("attempt-b");
    await act(async () => { poll.resolve([storedReply("attempt-a", { status: "completed" })]); await Promise.resolve(); });
    expect(useAgentStore.getState().activity?.attemptId).toBe("attempt-b");
    expect(useAgentStore.getState().status).toBe("streaming");
    expect(useAgentStore.getState().streamingText).toBe("Next attempt evidence");
  });

  it("does not attach a late goal or start its turn in another chat", async () => {
    const created = deferred<ReturnType<typeof goal>>();
    apiMock.createGoal.mockReturnValue(created.promise);
    const router = await mount("goal-a");
    enableGoal();
    submit();
    await waitFor(() => expect(apiMock.createGoal).toHaveBeenCalled());
    await act(async () => { await router.navigate("/?session=goal-b"); });
    startNextAttempt("pending-b");
    await act(async () => { created.resolve(goal("goal-a")); await Promise.resolve(); });
    expect(useAgentStore.getState().activity?.attemptId).toBe("pending-b");
    expect(apiMock.sendMessage).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Active research goal" })).toBeNull();
  });

  it("does not replace the current chat after a late goal session creation", async () => {
    const created = deferred<{ session_id: string }>();
    apiMock.createSession.mockReturnValue(created.promise);
    const router = await mount("");
    enableGoal();
    submit();
    await waitFor(() => expect(apiMock.createSession).toHaveBeenCalled());
    await act(async () => { await router.navigate("/?session=goal-b"); });
    startNextAttempt("pending-b");
    await act(async () => { created.resolve({ session_id: "late-goal-a" }); await Promise.resolve(); });
    expect(useAgentStore.getState().sessionId).toBe("goal-b");
    expect(useAgentStore.getState().activity?.attemptId).toBe("pending-b");
    expect(apiMock.createGoal).not.toHaveBeenCalled();
  });

  it("creates and starts a goal in its own newly created chat", async () => {
    const created = deferred<ReturnType<typeof goal>>();
    apiMock.createSession.mockResolvedValue({ session_id: "new-goal" });
    apiMock.createGoal.mockReturnValue(created.promise);
    apiMock.sendMessage.mockResolvedValue({ attempt_id: "goal-attempt" });
    await mount("");
    enableGoal();
    submit();
    await waitFor(() => expect(apiMock.createGoal).toHaveBeenCalledWith("new-goal", { objective: "Research this company" }));
    await act(async () => { created.resolve(goal("new-goal")); await Promise.resolve(); });
    await waitFor(() => expect(apiMock.sendMessage).toHaveBeenCalledWith("new-goal", expect.any(String)));
    expect(useAgentStore.getState().sessionId).toBe("new-goal");
    expect(useAgentStore.getState().activity?.attemptId).toBe("goal-attempt");
  });

  it("does not let an old goal read erase the goal just created", async () => {
    const prior = deferred<ReturnType<typeof goal> | null>();
    apiMock.getGoal.mockReturnValue(prior.promise);
    apiMock.createGoal.mockResolvedValue(goal("goal-a"));
    apiMock.sendMessage.mockResolvedValue({ attempt_id: "goal-attempt" });
    await mount("goal-a");
    enableGoal();
    submit();
    await waitFor(() => expect(useAgentStore.getState().activity?.attemptId).toBe("goal-attempt"));
    await act(async () => { prior.resolve(null); await Promise.resolve(); });
    expect(screen.getByRole("button", { name: "Active research goal" })).toBeInTheDocument();
  });

  it.each(["resolve", "reject"])("isolates a late goal continuation %s from another chat", async (outcome) => {
    apiMock.getGoal.mockImplementation((sid: string) => Promise.resolve(goal(sid)));
    const sent = deferred<{ attempt_id: string }>();
    apiMock.sendMessage.mockReturnValue(sent.promise);
    const router = await mount("continue-a");
    fireEvent.click(await screen.findByRole("button", { name: "Active research goal" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(apiMock.sendMessage).toHaveBeenCalled());
    await act(async () => { await router.navigate("/?session=continue-b"); });
    startNextAttempt("pending-b");
    await act(async () => {
      if (outcome === "resolve") sent.resolve({ attempt_id: "attempt-a" });
      else sent.reject(new Error("A failed"));
      await Promise.resolve();
    });
    expect(useAgentStore.getState().activity?.attemptId).toBe("pending-b");
    expect(useAgentStore.getState().status).toBe("streaming");
    expect(useAgentStore.getState().messages.some((message) => message.type === "error")).toBe(false);
  });

  it.each(["failed", "cancelled", "interrupted"])("keeps %s history visibly incomplete and does not display a success metrics card", async (status) => {
    apiMock.getSessionMessages.mockResolvedValue([storedReply("failed-a", { status, run_id: "failed-run", metrics: { total_return: 0.1 } })]);
    await mount("failed-history");
    await waitFor(() => expect(useAgentStore.getState().messages.length).toBeGreaterThan(0));
    expect(useAgentStore.getState().messages.find((message) => message.content === "Stored answer")?.type).toBe("error");
    expect(useAgentStore.getState().messages.some((message) => message.type === "run_complete")).toBe(false);
  });

  it.each(["failed", "cancelled"])("retains the durable %s partial once without rendering draft chart JSON", async (status) => {
    await mount(`partial-${status}`);
    const summary = "Incomplete and not verified.\n\n```chart\n{\"symbol\":\"MBB.VN\",\"bars\":[{\"c\":999999}]}\n```";
    act(() => { handlers()["attempt.started"]({ attempt_id: "partial-a" }); });
    act(() => { handlers()[`attempt.${status}`]({ attempt_id: "partial-a", summary, partial: true }); });
    act(() => { handlers()[`attempt.${status}`]({ attempt_id: "partial-a", summary, partial: true }); });
    const messages = useAgentStore.getState().messages.filter((message) => message.content === summary);
    expect(messages).toHaveLength(1);
    expect(messages[0].type).toBe("error");
    expect(document.querySelector("figure")).toBeNull();
    expect(useAgentStore.getState().status).toBe("idle");
  });
});
