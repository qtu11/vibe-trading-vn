import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { api } from "@/lib/api";
import type { ResearchObject } from "@/lib/research";
import type { ResearchRevision } from "@/lib/researchArtifacts";
import { CryptoBasisLab } from "../CryptoBasisLab";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/lib/api", () => ({ api: { researchCryptoBasis: vi.fn(), saveResearchRevision: vi.fn(), listResearchRevisions: vi.fn(), getResearchRevision: vi.fn(), diffResearchRevisions: vi.fn(), reviewResearchRevision: vi.fn() } }));
beforeEach(() => { Object.values(api).forEach((method) => vi.mocked(method).mockReset()); });

const result: ResearchObject = { ok: true, base: "CASE", quote: "USDT", as_of: "2026-11-06T08:00:00Z", input_sha256: "fixture-hash", verification_status: "user_supplied_unverified", summary: { total: 3, accepted: 2, rejected: 1 },
  rows: [
    { venue: "synthetic", instrument_id: "zero-basis", expiry: "2026-12-06T08:00:00Z", status: "accepted", basis_fraction: "0", annualized_basis: "0", annualized_lower_basis: "-0.01", annualized_upper_basis: "0.01", seconds_to_expiry: "2592000", reason_codes: [] },
    { venue: "synthetic", instrument_id: "negative-basis", expiry: "2027-01-05T08:00:00Z", status: "accepted", basis_fraction: "-0.01", annualized_basis: "-0.0608333333333", annualized_lower_basis: "-0.07", annualized_upper_basis: "-0.05", seconds_to_expiry: "5184000", reason_codes: [] },
    { venue: "synthetic", instrument_id: "perpetual-rejected", expiry: null, status: "rejected", basis_fraction: null, annualized_basis: null, annualized_lower_basis: null, annualized_upper_basis: null, seconds_to_expiry: null, reason_codes: ["perpetual_has_no_dated_basis", "expiry_missing"] },
  ], provenance: { source_refs: ["synthetic:quote"] }, limitations: ["Caller supplied, no source verification"] };

function input() { return screen.getByLabelText("valuationLab.input"); }
function sample() { fireEvent.click(screen.getByRole("button", { name: "valuationLab.example" })); }
async function calculate() {
  sample(); fireEvent.click(screen.getByRole("button", { name: "cryptoBasis.calculate" }));
  return screen.findByRole("region", { name: "cryptoBasis.result" });
}

it("starts empty and loads only an explicit synthetic input without a network call", () => {
  render(<CryptoBasisLab />);
  expect(input()).toHaveValue("");
  expect(screen.getByRole("button", { name: "cryptoBasis.calculate" })).toBeDisabled();
  sample(); const payload = JSON.parse((input() as HTMLTextAreaElement).value);
  expect(payload.base).toBe("CASE"); expect(payload.futures).toHaveLength(3);
  expect(payload.futures[2].kind).toBe("perpetual"); expect(payload.futures[2].expiry).toBeNull();
  expect(screen.getByText("valuationLab.synthetic")).toBeVisible();
  expect(Object.values(api).every((method) => vi.mocked(method).mock.calls.length === 0)).toBe(true);
});

it("keeps negative, zero and rejected null values distinct and declares the rate convention", async () => {
  vi.mocked(api.researchCryptoBasis).mockResolvedValue(result);
  render(<CryptoBasisLab />); const region = await calculate();
  expect(within(region).getByText("cryptoBasis.grossOnly")).toBeVisible();
  expect(within(region).getByText("cryptoBasis.annualization")).toBeVisible();
  const rows = within(region).getAllByRole("row");
  expect(within(rows[1]).getAllByText("0")).toHaveLength(2);
  expect(within(rows[2]).getByText("-0.0608333333333")).toBeVisible();
  expect(within(rows[3]).getAllByText("marketResearch.unknown")).toHaveLength(4);
  expect(within(rows[3]).queryByText("0")).not.toBeInTheDocument();
  expect(within(rows[3]).getByText("perpetual_has_no_dated_basis · expiry_missing")).toBeVisible();
  expect(api.researchCryptoBasis).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ base: "CASE", quote: "USDT" }), expect.any(AbortSignal));
  expect(api.saveResearchRevision).not.toHaveBeenCalled();
});

it("shows a fully rejected valid report without claiming any accepted curve", async () => {
  vi.mocked(api.researchCryptoBasis).mockResolvedValue({ ...result, summary: { total: 1, accepted: 0, rejected: 1 }, rows: [result.rows instanceof Array ? result.rows[2] : {}] });
  render(<CryptoBasisLab />); const region = await calculate();
  expect(within(region).getByText("CASE/USDT · cryptoBasis.accepted: 0 · cryptoBasis.rejected: 1")).toBeVisible();
  expect(within(region).queryByText("-0.0608333333333")).not.toBeInTheDocument();
});

it("invalidates and aborts late results when a draft changes", async () => {
  let resolve!: (value: ResearchObject) => void;
  vi.mocked(api.researchCryptoBasis).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<CryptoBasisLab />); sample();
  fireEvent.click(screen.getByRole("button", { name: "cryptoBasis.calculate" }));
  const signal = vi.mocked(api.researchCryptoBasis).mock.calls[0][1]!;
  fireEvent.change(input(), { target: { value: '{"newDraft":true}' } });
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(result); });
  expect(screen.queryByRole("region", { name: "cryptoBasis.result" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "researchRevision.save" })).toBeDisabled();
});

it("offers explicit cancellation and aborts pending reads on unmount", () => {
  vi.mocked(api.researchCryptoBasis).mockReturnValue(new Promise(() => {}));
  const { unmount } = render(<CryptoBasisLab />); sample();
  fireEvent.click(screen.getByRole("button", { name: "cryptoBasis.calculate" }));
  const first = vi.mocked(api.researchCryptoBasis).mock.calls[0][1]!;
  fireEvent.click(screen.getByRole("button", { name: "marketResearch.cancel" }));
  expect(first.aborted).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "cryptoBasis.calculate" }));
  const second = vi.mocked(api.researchCryptoBasis).mock.calls[1][1]!;
  unmount(); expect(second.aborted).toBe(true);
});

it("rejects nonobject or oversized input before an engine call", () => {
  render(<CryptoBasisLab />);
  fireEvent.change(input(), { target: { value: "[]" } });
  fireEvent.click(screen.getByRole("button", { name: "cryptoBasis.calculate" }));
  expect(screen.getByRole("alert")).toHaveTextContent("cryptoBasis.invalidInput");
  fireEvent.change(input(), { target: { value: '{"oversized":"' + "ạ".repeat(32000) + '"}' } });
  fireEvent.click(screen.getByRole("button", { name: "cryptoBasis.calculate" }));
  expect(api.researchCryptoBasis).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "researchRevision.save" })).toBeDisabled();
});

it("shows API errors without an inferred zero or a saveable report", async () => {
  vi.mocked(api.researchCryptoBasis).mockRejectedValue(new Error("quotes unavailable"));
  render(<CryptoBasisLab />); sample();
  fireEvent.click(screen.getByRole("button", { name: "cryptoBasis.calculate" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("quotes unavailable");
  expect(screen.queryByRole("region", { name: "cryptoBasis.result" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "researchRevision.save" })).toBeDisabled();
});

it("saves bare validated inputs separately and freezes writes without replaying a calculation", async () => {
  let resolve!: (value: ResearchRevision) => void;
  vi.mocked(api.researchCryptoBasis).mockResolvedValue(result);
  vi.mocked(api.saveResearchRevision).mockImplementation(() => new Promise((done) => { resolve = done; }));
  const onBusyChange = vi.fn(); render(<CryptoBasisLab onBusyChange={onBusyChange} />); await calculate();
  const submitted = JSON.parse((input() as HTMLTextAreaElement).value);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.save" }));
  expect(api.saveResearchRevision).toHaveBeenCalledExactlyOnceWith("crypto_basis", submitted, undefined, expect.stringMatching(/^rk_[0-9a-f]{32}$/));
  expect(input()).toBeDisabled(); expect(screen.getByRole("button", { name: "cryptoBasis.calculate" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "valuationLab.example" })).toBeDisabled();
  expect(onBusyChange).toHaveBeenLastCalledWith(true);
  await act(async () => { resolve({ revision_id: "rr_basis", kind: "crypto_basis", parent_revision_id: null, created_at: "fixture", scope: { base: "CASE", quote: "USDT" }, request: submitted, result, hashes: {}, producer: {}, content_scope: "one_bounded_basis_curve", verification_status: "user_supplied_unverified", review_state: "pending_review", review_history: [], limitations: [] }); });
  expect(await screen.findByRole("heading", { name: "rr_basis" })).toBeVisible();
  expect(input()).toBeEnabled(); expect(onBusyChange).toHaveBeenLastCalledWith(false);
  expect(api.researchCryptoBasis).toHaveBeenCalledTimes(1);
});

it("does not automatically retry a failed save and releases the input lock", async () => {
  vi.mocked(api.researchCryptoBasis).mockResolvedValue(result);
  vi.mocked(api.saveResearchRevision).mockRejectedValue(new Error("ambiguous write"));
  render(<CryptoBasisLab />); await calculate();
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("ambiguous write");
  await waitFor(() => expect(input()).toBeEnabled());
  expect(api.saveResearchRevision).toHaveBeenCalledTimes(1);
  expect(api.researchCryptoBasis).toHaveBeenCalledTimes(1);
});
