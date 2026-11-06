import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "@/lib/api";
import type { ResearchObject } from "@/lib/research";
import type { ResearchRevision, ResearchRevisionList } from "@/lib/researchArtifacts";
import { ResearchRevisionPanel } from "../ResearchRevisionPanel";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/lib/api", () => ({ api: { saveResearchRevision: vi.fn(), listResearchRevisions: vi.fn(), getResearchRevision: vi.fn(), diffResearchRevisions: vi.fn(), reviewResearchRevision: vi.fn() } }));
beforeEach(() => { Object.values(api).forEach((method) => vi.mocked(method).mockReset()); });

const request: ResearchObject = { symbol: "CASE.VN", currency: "VND" };
function revision(id = "rr_saved", overrides: Partial<ResearchRevision> = {}): ResearchRevision {
  return { revision_id: id, parent_revision_id: null, kind: "vietnam_dcf", created_at: "2026-11-06T00:00:00Z",
    scope: { symbol: "CASE.VN", consolidation: "consolidated" }, request, result: { ok: true }, hashes: {}, producer: {},
    content_scope: "one_bounded_dcf_scenario", verification_status: "user_supplied_unverified", review_state: "unreviewed",
    review_history: [], limitations: ["A review is a self-reported operator acknowledgment; evidence remains unverified."], ...overrides };
}
function listing(...ids: string[]): ResearchRevisionList {
  return { items: ids.map((id) => revision(id)), total: ids.length, next_offset: null };
}
async function history(...ids: string[]) {
  vi.mocked(api.listResearchRevisions).mockResolvedValue(listing(...ids));
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.history" }));
  await screen.findByRole("button", { name: new RegExp(ids[0]) });
}
async function save() {
  vi.mocked(api.saveResearchRevision).mockResolvedValue(revision());
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.save" }));
  await screen.findByRole("heading", { name: "rr_saved" });
}

it("does not read or write on mount and cannot save without evaluated inputs", () => {
  const { rerender } = render(<ResearchRevisionPanel kind="vietnam_dcf" request={null} />);
  expect(screen.getByRole("button", { name: "researchRevision.save" })).toBeDisabled();
  expect(Object.values(api).every((method) => vi.mocked(method).mock.calls.length === 0)).toBe(true);
  rerender(<ResearchRevisionPanel kind="vietnam_dcf" request={request} />);
  expect(screen.getByRole("button", { name: "researchRevision.save" })).toBeEnabled();
  expect(api.saveResearchRevision).not.toHaveBeenCalled();
});

it("saves one immutable request deliberately and preserves its unverified state", async () => {
  const onBusyChange = vi.fn();
  render(<ResearchRevisionPanel kind="vietnam_dcf" request={request} onBusyChange={onBusyChange} />);
  await save();
  expect(api.saveResearchRevision).toHaveBeenCalledExactlyOnceWith("vietnam_dcf", request, undefined, expect.stringMatching(/^rk_[0-9a-f]{32}$/));
  expect(screen.getByText(/unreviewed · user_supplied_unverified · one_bounded_dcf_scenario/)).toBeVisible();
  expect(onBusyChange.mock.calls).toEqual([[true], [false]]);
  expect(api.getResearchRevision).not.toHaveBeenCalled();
});

it("blocks repeated clicks while a save is pending", async () => {
  let resolve!: (value: ResearchRevision) => void;
  vi.mocked(api.saveResearchRevision).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<ResearchRevisionPanel kind="vietnam_dcf" request={request} />);
  const button = screen.getByRole("button", { name: "researchRevision.save" });
  fireEvent.click(button); fireEvent.click(button);
  expect(api.saveResearchRevision).toHaveBeenCalledTimes(1);
  expect(button).toBeDisabled();
  expect(screen.getByLabelText("researchRevision.parent")).toBeDisabled();
  await act(async () => { resolve(revision()); });
  expect(button).toBeEnabled();
});

it("never automatically retries an uncertain save or infers success", async () => {
  vi.mocked(api.saveResearchRevision).mockRejectedValue(new Error("Connection closed after submission"));
  render(<ResearchRevisionPanel kind="vietnam_dcf" request={request} />);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("researchRevision.uncertain");
  expect(api.saveResearchRevision).toHaveBeenCalledTimes(1);
  expect(api.listResearchRevisions).not.toHaveBeenCalled();
  expect(api.getResearchRevision).not.toHaveBeenCalled();
  expect(screen.queryByRole("heading", { name: "rr_saved" })).not.toBeInTheDocument();
});

it("reuses a frozen operation key only for a deliberate retry of the same request", async () => {
  vi.mocked(api.saveResearchRevision).mockRejectedValueOnce(new Error("Unknown write outcome")).mockResolvedValueOnce(revision());
  render(<ResearchRevisionPanel kind="vietnam_dcf" request={request} />);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.save" }));
  await screen.findByRole("alert");
  const originalKey = vi.mocked(api.saveResearchRevision).mock.calls[0][3];
  expect(originalKey).toMatch(/^rk_[0-9a-f]{32}$/);
  expect(api.saveResearchRevision).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.save" }));
  await screen.findByRole("heading", { name: "rr_saved" });
  expect(api.saveResearchRevision).toHaveBeenLastCalledWith("vietnam_dcf", request, undefined, originalKey);
});

it("creates a different key for an explicit new intent after an unresolved write", async () => {
  vi.mocked(api.saveResearchRevision).mockRejectedValue(new Error("Unknown write outcome"));
  render(<ResearchRevisionPanel kind="vietnam_dcf" request={request} />);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.save" }));
  await screen.findByRole("alert");
  const first = vi.mocked(api.saveResearchRevision).mock.calls[0][3];
  fireEvent.click(screen.getByRole("button", { name: "researchAttempt.newIntent" }));
  expect(api.saveResearchRevision).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.save" }));
  await waitFor(() => expect(api.saveResearchRevision).toHaveBeenCalledTimes(2));
  expect(vi.mocked(api.saveResearchRevision).mock.calls[1][3]).not.toBe(first);
});

it("does not replay an old key after the evaluated request changes", async () => {
  vi.mocked(api.saveResearchRevision).mockRejectedValue(new Error("Unknown write outcome"));
  const { rerender } = render(<ResearchRevisionPanel kind="vietnam_dcf" request={request} />);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.save" })); await screen.findByRole("alert");
  const key = vi.mocked(api.saveResearchRevision).mock.calls[0][3];
  rerender(<ResearchRevisionPanel kind="vietnam_dcf" request={{ ...request, symbol: "NEW.VN" }} />);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.save" }));
  await waitFor(() => expect(api.saveResearchRevision).toHaveBeenCalledTimes(2));
  expect(vi.mocked(api.saveResearchRevision).mock.calls[1][1]).toEqual({ ...request, symbol: "NEW.VN" });
  expect(vi.mocked(api.saveResearchRevision).mock.calls[1][3]).not.toBe(key);
});

it("records an explicit self-reported review without upgrading source verification", async () => {
  vi.mocked(api.reviewResearchRevision).mockResolvedValue({ receipt: "self_reported" });
  vi.mocked(api.getResearchRevision).mockResolvedValue(revision("rr_saved", { review_state: "acknowledged" }));
  render(<ResearchRevisionPanel kind="vietnam_dcf" request={request} />);
  await save();
  expect(api.reviewResearchRevision).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("researchRevision.reviewer"), { target: { value: "Local operator" } });
  fireEvent.change(screen.getByLabelText("researchRevision.note"), { target: { value: "Reviewed assumptions; sources still unverified." } });
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.review" }));
  await waitFor(() => expect(api.reviewResearchRevision).toHaveBeenCalledExactlyOnceWith("rr_saved", "acknowledged", "Reviewed assumptions; sources still unverified.", "Local operator"));
  expect(await screen.findByText(/acknowledged · user_supplied_unverified/)).toBeVisible();
  expect(screen.getByText("researchRevision.reviewSaved")).toBeVisible();
  expect(screen.getByLabelText("researchRevision.note")).toHaveValue("");
});

it("requires a reviewer and note, and does not retry a failed review", async () => {
  vi.mocked(api.reviewResearchRevision).mockRejectedValue(new Error("Review outcome unknown"));
  render(<ResearchRevisionPanel kind="vietnam_dcf" request={request} />); await save();
  const button = screen.getByRole("button", { name: "researchRevision.review" });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("researchRevision.reviewer"), { target: { value: "Operator" } });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("researchRevision.note"), { target: { value: "Needs changes" } });
  fireEvent.change(screen.getByLabelText("researchRevision.decision"), { target: { value: "changes_requested" } });
  fireEvent.click(button);
  expect(await screen.findByRole("alert")).toHaveTextContent("researchRevision.uncertain");
  expect(api.reviewResearchRevision).toHaveBeenCalledExactlyOnceWith("rr_saved", "changes_requested", "Needs changes", "Operator");
  expect(api.getResearchRevision).not.toHaveBeenCalled();
  expect(screen.getByText(/unreviewed · user_supplied_unverified/)).toBeVisible();
});

it("retains a successful review receipt if its separate refresh fails", async () => {
  vi.mocked(api.reviewResearchRevision).mockResolvedValue({ receipt: "self_reported" });
  vi.mocked(api.getResearchRevision).mockRejectedValue(new Error("Refresh unavailable"));
  render(<ResearchRevisionPanel kind="vietnam_dcf" request={request} />); await save();
  fireEvent.change(screen.getByLabelText("researchRevision.reviewer"), { target: { value: "Operator" } });
  fireEvent.change(screen.getByLabelText("researchRevision.note"), { target: { value: "Read" } });
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.review" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Refresh unavailable");
  expect(screen.getByText("researchRevision.reviewSaved")).toBeVisible();
  expect(api.reviewResearchRevision).toHaveBeenCalledTimes(1);
});

it("aborts a pending diff when its before-selection changes and ignores the old response", async () => {
  let resolve!: (value: ResearchObject) => void;
  vi.mocked(api.getResearchRevision).mockResolvedValue(revision("rr_current"));
  vi.mocked(api.diffResearchRevisions).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<ResearchRevisionPanel kind="vietnam_dcf" request={request} />);
  await history("rr_current", "rr_before_a", "rr_before_b");
  fireEvent.click(screen.getByRole("button", { name: /rr_current/ }));
  await screen.findByRole("heading", { name: "rr_current" });
  fireEvent.change(screen.getByLabelText("researchRevision.before"), { target: { value: "rr_before_a" } });
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.compare" }));
  const signal = vi.mocked(api.diffResearchRevisions).mock.calls[0][2]!;
  fireEvent.change(screen.getByLabelText("researchRevision.before"), { target: { value: "rr_before_b" } });
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve({ marker: "stale_diff_result" }); });
  expect(screen.queryByText(/stale_diff_result/)).not.toBeInTheDocument();
  expect(screen.getByLabelText("researchRevision.before")).toHaveValue("rr_before_b");
  expect(screen.getByRole("button", { name: "researchRevision.compare" })).toBeEnabled();
});

it("ignores a late revision read after a newer selection", async () => {
  let resolve!: (value: ResearchRevision) => void;
  vi.mocked(api.getResearchRevision).mockImplementationOnce(() => new Promise((done) => { resolve = done; })).mockResolvedValueOnce(revision("rr_new"));
  render(<ResearchRevisionPanel kind="vietnam_dcf" request={request} />);
  await history("rr_old", "rr_new");
  fireEvent.click(screen.getByRole("button", { name: /rr_old/ }));
  const signal = vi.mocked(api.getResearchRevision).mock.calls[0][1]!;
  fireEvent.click(screen.getByRole("button", { name: /rr_new/ }));
  await screen.findByRole("heading", { name: "rr_new" });
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(revision("rr_old")); });
  expect(screen.queryByRole("heading", { name: "rr_old" })).not.toBeInTheDocument();
});

it("does not let an older read replace a new save receipt", async () => {
  let resolve!: (value: ResearchRevision) => void;
  vi.mocked(api.getResearchRevision).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<ResearchRevisionPanel kind="vietnam_dcf" request={request} />);
  await history("rr_old"); fireEvent.click(screen.getByRole("button", { name: /rr_old/ }));
  const signal = vi.mocked(api.getResearchRevision).mock.calls[0][1]!;
  await save();
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(revision("rr_old")); });
  expect(screen.getByRole("heading", { name: "rr_saved" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "rr_old" })).not.toBeInTheDocument();
});

it("cancels a previous kind's history and clears its lineage state", async () => {
  let resolve!: (value: ResearchRevisionList) => void;
  vi.mocked(api.listResearchRevisions).mockImplementation(() => new Promise((done) => { resolve = done; }));
  const { rerender } = render(<ResearchRevisionPanel kind="vietnam_dcf" request={request} />);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.history" }));
  const signal = vi.mocked(api.listResearchRevisions).mock.calls[0][2]!;
  rerender(<ResearchRevisionPanel kind="vietnam_comparables" request={null} />);
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(listing("rr_old_kind")); });
  expect(screen.queryByRole("button", { name: /rr_old_kind/ })).not.toBeInTheDocument();
  expect(screen.getByLabelText("researchRevision.parent")).toHaveValue("");
});
