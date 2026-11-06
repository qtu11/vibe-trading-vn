import { act, fireEvent, render, screen } from "@testing-library/react";
import { api } from "@/lib/api";
import type { ResearchObject } from "@/lib/research";
import { VietnamReverseDCFLab } from "../VietnamReverseDCFLab";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/lib/api", () => ({ api: { researchVietnamReverseDCF: vi.fn(), saveResearchRevision: vi.fn() } }));
beforeEach(() => vi.clearAllMocks());
function sample() { fireEvent.click(screen.getByRole("button", { name: "valuationLab.example" })); }
function calculate() { fireEvent.click(screen.getByRole("button", { name: "reverseDCF.calculate" })); }
const result: ResearchObject = { ok: true, solver: { status: "solved", implied_terminal_growth: 0, repriced_value_per_share_vnd: 100, residual_vnd_per_share: 0, reason: null }, verification_status: "user_supplied_unverified" };

it("requires explicit calculation and preserves zero implied growth and residual", async () => {
  vi.mocked(api.researchVietnamReverseDCF).mockResolvedValue(result);
  render(<VietnamReverseDCFLab />); sample();
  expect(api.researchVietnamReverseDCF).not.toHaveBeenCalled(); calculate();
  expect(await screen.findByRole("region", { name: "reverseDCF.result" })).toHaveTextContent("solved");
  expect(screen.getAllByText("0")).toHaveLength(2);
  expect(api.saveResearchRevision).not.toHaveBeenCalled();
  expect(api.researchVietnamReverseDCF).toHaveBeenCalledWith(expect.objectContaining({ schema_version: 1, dcf: expect.objectContaining({ symbol: "CASE.VN" }) }), expect.any(AbortSignal));
});

it("renders an unreachable target as unknown with the retained reason", async () => {
  vi.mocked(api.researchVietnamReverseDCF).mockResolvedValue({ ok: true, solver: { status: "outside_bracket", implied_terminal_growth: null, repriced_value_per_share_vnd: null, residual_vnd_per_share: null, reason: "target_outside_supplied_bracket" } });
  render(<VietnamReverseDCFLab />); sample(); calculate();
  expect(await screen.findByText("target_outside_supplied_bracket")).toBeVisible();
  expect(screen.getAllByText("marketResearch.unknown")).toHaveLength(3);
  expect(screen.queryByText("0")).not.toBeInTheDocument();
});

it("cancels and ignores a result after the scenario changes", async () => {
  let resolve!: (value: ResearchObject) => void;
  vi.mocked(api.researchVietnamReverseDCF).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<VietnamReverseDCFLab />); sample(); calculate();
  const signal = vi.mocked(api.researchVietnamReverseDCF).mock.calls[0][1]!;
  fireEvent.change(screen.getByLabelText("valuationLab.input"), { target: { value: "{}" } });
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(result));
  expect(screen.queryByRole("region", { name: "reverseDCF.result" })).not.toBeInTheDocument();
});

it("separates revision save from read and freezes the scenario during an uncertain write", async () => {
  vi.mocked(api.researchVietnamReverseDCF).mockResolvedValue(result);
  let reject!: (reason: Error) => void;
  vi.mocked(api.saveResearchRevision).mockImplementation(() => new Promise((_, fail) => { reject = fail; }));
  render(<VietnamReverseDCFLab />); sample(); calculate();
  await screen.findByRole("region", { name: "reverseDCF.result" });
  const input = JSON.parse((screen.getByLabelText("valuationLab.input") as HTMLTextAreaElement).value);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.save" }));
  expect(api.saveResearchRevision).toHaveBeenCalledWith("vietnam_reverse_dcf", input, undefined, expect.stringMatching(/^rk_[0-9a-f]{32}$/));
  expect(screen.getByLabelText("valuationLab.input")).toBeDisabled();
  expect(screen.getByRole("button", { name: "valuationLab.example" })).toBeDisabled();
  await act(async () => reject(new Error("uncertain outcome")));
  expect(screen.getByRole("alert")).toHaveTextContent("uncertain outcome");
  expect(api.saveResearchRevision).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("valuationLab.input")).toBeEnabled();
});
