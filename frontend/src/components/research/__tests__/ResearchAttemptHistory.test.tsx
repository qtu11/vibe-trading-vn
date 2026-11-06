import { act, fireEvent, render, screen } from "@testing-library/react";
import { api } from "@/lib/api";
import type { ResearchAttemptList } from "@/lib/researchArtifacts";
import { ResearchAttemptHistory } from "../ResearchAttemptHistory";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/lib/api", () => ({ api: { listResearchAttempts: vi.fn() } }));
beforeEach(() => vi.clearAllMocks());
const parent = "rr_" + "a".repeat(32), key = "rk_" + "b".repeat(32);
function data(status: "failed" | "in_flight_unknown" | "succeeded" = "failed"): ResearchAttemptList {
  return { items: [{ attempt_id: "attempt-1", kind: "vietnam_dcf", parent_revision_id: parent, idempotency_key: key,
    status, created_at: "2026-11-06T00:00:00Z", finished_at: status === "in_flight_unknown" ? null : "2026-11-06T00:00:01Z",
    revision_id: status === "succeeded" ? "rr_" + "c".repeat(32) : null, error: status === "failed" ? { code: "RESEARCH_FAILED", message: "Source unavailable" } : null }],
    total: 1, next_offset: null, refresh_state: { parent_revision_id: parent, last_attempt: null, last_good_revision_id: parent,
      state: status === "failed" ? "refresh_failed" : status === "succeeded" ? "superseded" : "refresh_in_flight_unknown" } };
}

it("reads only deliberately and scopes failed refreshes to the selected saved revision", async () => {
  vi.mocked(api.listResearchAttempts).mockResolvedValue(data());
  render(<ResearchAttemptHistory kind="vietnam_dcf" revisionId={parent} operationKey={key} disabled={false} onOpen={vi.fn()} />);
  expect(api.listResearchAttempts).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("researchAttempt.scope"), { target: { value: "revision" } });
  fireEvent.click(screen.getByRole("button", { name: "researchAttempt.read" }));
  expect(await screen.findByText("researchAttempt.refresh_failed")).toBeVisible();
  expect(screen.getByText("RESEARCH_FAILED · Source unavailable")).toBeVisible();
  expect(api.listResearchAttempts).toHaveBeenCalledExactlyOnceWith("vietnam_dcf", parent, undefined, 0, expect.any(AbortSignal));
});

it("keeps an unfinished attempt unknown and can look up the original key", async () => {
  vi.mocked(api.listResearchAttempts).mockResolvedValue(data("in_flight_unknown"));
  render(<ResearchAttemptHistory kind="vietnam_dcf" revisionId={parent} operationKey={key} disabled={false} onOpen={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("researchAttempt.scope"), { target: { value: "key" } });
  fireEvent.click(screen.getByRole("button", { name: "researchAttempt.read" }));
  expect(await screen.findByText(/^researchAttempt.in_flight_unknown ·/)).toBeVisible();
  expect(screen.queryByText("researchAttempt.failed")).not.toBeInTheDocument();
  expect(api.listResearchAttempts).toHaveBeenCalledWith("vietnam_dcf", undefined, key, 0, expect.any(AbortSignal));
});

it("aborts a stale scoped response when the saved revision changes or writing begins", async () => {
  let resolve!: (value: ResearchAttemptList) => void;
  vi.mocked(api.listResearchAttempts).mockImplementation(() => new Promise((done) => { resolve = done; }));
  const props = { kind: "vietnam_dcf" as const, revisionId: parent, operationKey: key, disabled: false, onOpen: vi.fn() };
  const { rerender } = render(<ResearchAttemptHistory {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "researchAttempt.read" }));
  const signal = vi.mocked(api.listResearchAttempts).mock.calls[0][4]!;
  rerender(<ResearchAttemptHistory {...props} disabled />);
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(data()));
  expect(screen.queryByText("attempt-1")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "researchAttempt.read" })).toBeDisabled();
});

it("opens the exact saved successor without inventing a result from failure metadata", async () => {
  vi.mocked(api.listResearchAttempts).mockResolvedValue(data("succeeded"));
  const onOpen = vi.fn();
  render(<ResearchAttemptHistory kind="vietnam_dcf" revisionId={parent} operationKey={key} disabled={false} onOpen={onOpen} />);
  fireEvent.click(screen.getByRole("button", { name: "researchAttempt.read" }));
  const id = "rr_" + "c".repeat(32);
  fireEvent.click(await screen.findByRole("button", { name: id }));
  expect(onOpen).toHaveBeenCalledExactlyOnceWith(id);
});
