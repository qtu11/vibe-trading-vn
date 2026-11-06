import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { api } from "@/lib/api";
import type { ResearchObject } from "@/lib/research";
import type { ResearchRevision } from "@/lib/researchArtifacts";
import { VietnamValuationLab } from "../VietnamValuationLab";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/lib/api", () => ({ api: { researchVietnamDCF: vi.fn(), researchVietnamComparables: vi.fn(), saveResearchRevision: vi.fn(), listResearchRevisions: vi.fn(), getResearchRevision: vi.fn(), diffResearchRevisions: vi.fn(), reviewResearchRevision: vi.fn() } }));
beforeEach(() => { Object.values(api).forEach((method) => vi.mocked(method).mockReset()); });

const dcf: ResearchObject = { ok: true, symbol: "CASE.VN", currency: "VND", base_case: { enterprise_value: 0, equity_value: null, value_per_share: 0 },
  sensitivity: { terminal_value_method: "perpetuity_growth", cells: [[{ wacc: 0.1, terminal_growth: 0.02, value_per_share_vnd: 0, reason: null },
    { wacc: 0.1, terminal_growth: 0.1, value_per_share_vnd: null, reason: "growth_must_be_below_wacc" }]] },
  excluded_restricted_cash_vnd: 7_000_000, limitations: ["Caller-declared and unverified synthetic scenario"] };
const comparables: ResearchObject = { ok: true, target: { symbol: "CASE.VN", eps_vnd: { value: 0, reason: "non_positive_per_share_denominator" }, bvps_vnd: { value: null, reason: "missing_input" } },
  distribution: { pe: { count: 0, median: null } }, paging: { next_offset: 3 }, aggregate_scope: "All supplied peers", sector_mismatches: [] };
function input() { return screen.getByLabelText("valuationLab.input"); }
function sample(method: "dcf" | "comparables") {
  fireEvent.change(screen.getByLabelText("valuationLab.method"), { target: { value: method } });
  fireEvent.click(screen.getByRole("button", { name: "valuationLab.example" }));
}
async function calculate(method: "dcf" | "comparables") {
  sample(method);
  fireEvent.click(screen.getByRole("button", { name: "valuationLab.calculate" }));
  return screen.findByRole("region", { name: "valuationLab.result" });
}

it("loads samples without automatically reading, evaluating, or saving", () => {
  render(<VietnamValuationLab />);
  expect(screen.getByRole("button", { name: "valuationLab.calculate" })).toBeDisabled();
  sample("dcf");
  const payload = JSON.parse((input() as HTMLTextAreaElement).value);
  expect(payload.symbol).toBe("CASE.VN");
  expect(payload.currency).toBe("VND");
  expect(payload.equity_bridge.restricted_cash).toBe("7");
  expect(Object.values(api).every((method) => vi.mocked(method).mock.calls.length === 0)).toBe(true);
  expect(screen.getByText("valuationLab.synthetic")).toBeVisible();
});

it("uses actual DCF field names and distinguishes zero, unknown and invalid grid reasons", async () => {
  vi.mocked(api.researchVietnamDCF).mockResolvedValue(dcf);
  render(<VietnamValuationLab />);
  const region = await calculate("dcf");
  expect(within(region).getAllByText("0")).toHaveLength(3);
  expect(within(region).getAllByText("marketResearch.unknown")).toHaveLength(2);
  expect(within(region).getByText("growth_must_be_below_wacc")).toBeVisible();
  expect(within(region).getByText("valuationLab.conditional")).toBeVisible();
  expect(within(region).getByText("valuationLab.gridExplanation")).toBeVisible();
  expect(api.researchVietnamDCF).toHaveBeenCalledWith(expect.objectContaining({ symbol: "CASE.VN", amount_scale: 1_000_000 }), expect.any(AbortSignal));
  expect(api.saveResearchRevision).not.toHaveBeenCalled();
});

it("renders comparables without turning an absent BVPS into zero and pages deliberately", async () => {
  vi.mocked(api.researchVietnamComparables).mockResolvedValue(comparables);
  render(<VietnamValuationLab />);
  const region = await calculate("comparables");
  expect(within(region).getByText("CASE.VN · EPS 0 VND · BVPS marketResearch.unknown VND")).toBeVisible();
  expect(api.researchVietnamComparables).toHaveBeenCalledWith(expect.any(Object), 0, expect.any(AbortSignal));
  fireEvent.click(screen.getByRole("button", { name: "valuationLab.nextPeers" }));
  await waitFor(() => expect(api.researchVietnamComparables).toHaveBeenLastCalledWith(expect.any(Object), 3, expect.any(AbortSignal)));
  expect(api.saveResearchRevision).not.toHaveBeenCalled();
});

it("aborts and ignores late calculations after a draft edit", async () => {
  let resolve!: (value: ResearchObject) => void;
  vi.mocked(api.researchVietnamDCF).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<VietnamValuationLab />); sample("dcf");
  fireEvent.click(screen.getByRole("button", { name: "valuationLab.calculate" }));
  const signal = vi.mocked(api.researchVietnamDCF).mock.calls[0][1]!;
  fireEvent.change(input(), { target: { value: '{"newDraft":true}' } });
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(dcf); });
  expect(screen.queryByRole("region", { name: "valuationLab.result" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "researchRevision.save" })).toBeDisabled();
});

it("cancels requests on a method change and never relabels an old result", async () => {
  let resolve!: (value: ResearchObject) => void;
  vi.mocked(api.researchVietnamDCF).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<VietnamValuationLab />); sample("dcf");
  fireEvent.click(screen.getByRole("button", { name: "valuationLab.calculate" }));
  const signal = vi.mocked(api.researchVietnamDCF).mock.calls[0][1]!;
  fireEvent.change(screen.getByLabelText("valuationLab.method"), { target: { value: "comparables" } });
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(dcf); });
  expect(input()).toHaveValue("");
  expect(screen.queryByRole("region", { name: "valuationLab.result" })).not.toBeInTheDocument();
  expect(api.researchVietnamComparables).not.toHaveBeenCalled();
});

it("offers explicit cancellation and aborts the next request on unmount", () => {
  vi.mocked(api.researchVietnamDCF).mockReturnValue(new Promise(() => {}));
  const { unmount } = render(<VietnamValuationLab />); sample("dcf");
  fireEvent.click(screen.getByRole("button", { name: "valuationLab.calculate" }));
  const first = vi.mocked(api.researchVietnamDCF).mock.calls[0][1]!;
  fireEvent.click(screen.getByRole("button", { name: "marketResearch.cancel" }));
  expect(first.aborted).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "valuationLab.calculate" }));
  const second = vi.mocked(api.researchVietnamDCF).mock.calls[1][1]!;
  unmount(); expect(second.aborted).toBe(true);
});

it("refuses invalid JSON before contacting an engine and never exposes a save action", () => {
  render(<VietnamValuationLab />);
  fireEvent.change(input(), { target: { value: "[]" } });
  fireEvent.click(screen.getByRole("button", { name: "valuationLab.calculate" }));
  expect(screen.getByRole("alert")).toHaveTextContent("valuationLab.invalidInput");
  expect(api.researchVietnamComparables).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "researchRevision.save" })).toBeDisabled();
});

it("shows provider or model failures without a successful valuation or inferred zero", async () => {
  vi.mocked(api.researchVietnamDCF).mockResolvedValue({ ok: false, error: "WACC bridge missing" });
  render(<VietnamValuationLab />); sample("dcf");
  fireEvent.click(screen.getByRole("button", { name: "valuationLab.calculate" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("WACC bridge missing");
  expect(screen.queryByRole("region", { name: "valuationLab.result" })).not.toBeInTheDocument();
  expect(api.saveResearchRevision).not.toHaveBeenCalled();
});

it("saves DCF inputs in a separate action and freezes the submitted draft during that write", async () => {
  let resolve!: (value: ResearchRevision) => void;
  vi.mocked(api.researchVietnamDCF).mockResolvedValue(dcf);
  vi.mocked(api.saveResearchRevision).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<VietnamValuationLab />); await calculate("dcf");
  const submitted = JSON.parse((input() as HTMLTextAreaElement).value);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.save" }));
  expect(api.saveResearchRevision).toHaveBeenCalledExactlyOnceWith("vietnam_dcf", submitted, undefined, expect.stringMatching(/^rk_[0-9a-f]{32}$/));
  expect(input()).toBeDisabled();
  expect(screen.getByLabelText("valuationLab.method")).toBeDisabled();
  expect(screen.getByRole("button", { name: "valuationLab.calculate" })).toBeDisabled();
  await act(async () => { resolve({ revision_id: "rr_dcf", parent_revision_id: null, kind: "vietnam_dcf", created_at: "fixture", scope: {}, request: submitted,
    result: dcf, hashes: {}, producer: {}, content_scope: "one_bounded_dcf_scenario", verification_status: "user_supplied_unverified", review_state: "unreviewed", review_history: [], limitations: [] }); });
  expect(await screen.findByRole("heading", { name: "rr_dcf" })).toBeVisible();
  expect(input()).toBeEnabled();
  expect(api.researchVietnamDCF).toHaveBeenCalledTimes(1);
});

it("saves the actual comparables page offset rather than implying all peers were displayed", async () => {
  vi.mocked(api.researchVietnamComparables).mockResolvedValue(comparables);
  vi.mocked(api.saveResearchRevision).mockRejectedValue(new Error("Fixture-only save failure"));
  render(<VietnamValuationLab />); await calculate("comparables");
  fireEvent.click(screen.getByRole("button", { name: "valuationLab.nextPeers" }));
  await waitFor(() => expect(api.researchVietnamComparables).toHaveBeenCalledTimes(2));
  await screen.findByRole("region", { name: "valuationLab.result" });
  const submitted = JSON.parse((input() as HTMLTextAreaElement).value);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.save" }));
  await screen.findByRole("alert");
  expect(api.saveResearchRevision).toHaveBeenCalledExactlyOnceWith("vietnam_comparables", { payload: submitted, offset: 3 }, undefined, expect.stringMatching(/^rk_[0-9a-f]{32}$/));
});
