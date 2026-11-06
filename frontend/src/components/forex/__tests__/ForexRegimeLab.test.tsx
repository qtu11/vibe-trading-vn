import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import i18n from "@/i18n";
import { api } from "@/lib/api";
import type { ResearchObject } from "@/lib/research";
import example from "@/data/research/forex-regime.example.json?raw";
import { ForexRegimeLab, parseRegimeRequest } from "../ForexRegimeLab";

vi.mock("@/lib/api", () => ({ api: { forexRegime: vi.fn() } }));
beforeAll(async () => { await i18n.changeLanguage("en"); });
beforeEach(() => { vi.mocked(api.forexRegime).mockReset(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const evaluation: ResearchObject = {
  status: "ok", code: null, experiment_kind: "causal_atr_sma_regime", regime_version: 1,
  source_verification: "caller_supplied_unverified", dataset_hash: "a".repeat(64), config_hash: "b".repeat(64),
  calibration: { train_end_index: 39, last_training_available_at: "2025-01-02T16:00:00Z", first_decision_available_at: "2025-01-02T17:00:00Z", entry_threshold: .75, exit_threshold: .25, feature_count: 32 },
  summary: { evaluated_bars: 56, unknown_bars: 1, neutral_bars: 55, transition_count: 1 },
  latest: { regime: "neutral", available_at: "2025-01-05T00:00:00Z", reason: "hysteresis_hold" },
  timeline: [{ index: 0, available_at: "2025-01-01T01:00:00Z", phase: "training", normalized_slope: null, regime: "unknown", reason: "training_only", dwell_remaining: 0 },
    { index: 1, available_at: "2025-01-01T02:00:00Z", phase: "training", normalized_slope: -.5, regime: "unknown", reason: "training_only", dwell_remaining: 0 }],
  paging: { offset: 0, limit: 2, total: 96, returned: 2, next_offset: 2 },
};
const label = (key: string) => i18n.t(`forexRegime.${key}`);
function loadExample() { fireEvent.click(screen.getByRole("button", { name: label("example") })); }
async function replay() {
  loadExample();
  fireEvent.click(screen.getByRole("button", { name: label("calculate") }));
  return screen.findByRole("region", { name: label("calibration") });
}
function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(blob);
  });
}

it("previews only bounded object requests and leaves financial validation to the server", () => {
  expect(parseRegimeRequest(example)).toEqual(JSON.parse(example));
  for (const value of ["null", "[]", "{}", JSON.stringify({ bars: Array(31).fill({}) }), JSON.stringify({ bars: Array(2001).fill({}) })]) {
    expect(() => parseRegimeRequest(value)).toThrow();
  }
  expect(() => parseRegimeRequest(JSON.stringify({ bars: Array(32).fill({}), note: "é".repeat(1024 * 1024) }))).toThrow("too_large");
});

it("replays only on request and preserves unknown, negative and zero values", async () => {
  vi.mocked(api.forexRegime).mockResolvedValue(evaluation);
  render(<ForexRegimeLab />);
  expect(api.forexRegime).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: label("calculate") })).toBeDisabled();
  await replay();
  expect(api.forexRegime).toHaveBeenCalledExactlyOnceWith(JSON.parse(example), expect.any(AbortSignal));
  expect(screen.getByText(label("synthetic"))).toBeVisible();
  const table = screen.getByRole("table", { name: label("timeline") });
  expect(within(table).getByRole("cell", { name: label("unknown") })).toBeVisible();
  expect(within(table).getByRole("cell", { name: "-0.5" })).toBeVisible();
  expect(within(table).getAllByRole("cell", { name: "0" })).toHaveLength(2);
  expect(screen.getByText(label("limits"))).toBeVisible();
});

it("keeps insufficient calibration unknown without inventing entry or exit thresholds", async () => {
  vi.mocked(api.forexRegime).mockResolvedValue({ ...evaluation, status: "incomplete", code: "INSUFFICIENT_CALIBRATION_FEATURES",
    calibration: { ...evaluation.calibration as ResearchObject, entry_threshold: null, exit_threshold: null },
    latest: { regime: "unknown", reason: "calibration_unavailable", available_at: "2025-01-05T00:00:00Z" } });
  render(<ForexRegimeLab />);
  const calibration = await replay();
  expect(screen.getByText(`${label("unavailable")} INSUFFICIENT_CALIBRATION_FEATURES`)).toBeVisible();
  expect(within(calibration).getAllByText(label("unknown"))).toHaveLength(2);
  expect(screen.getByRole("region", { name: label("latest") })).toHaveTextContent("unknown");
});

it("aborts changed inputs and ignores a late successful response", async () => {
  let resolve!: (value: ResearchObject) => void;
  vi.mocked(api.forexRegime).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<ForexRegimeLab />); loadExample();
  fireEvent.click(screen.getByRole("button", { name: label("calculate") }));
  const signal = vi.mocked(api.forexRegime).mock.calls[0][1]!;
  fireEvent.change(screen.getByLabelText(label("input")), { target: { value: "{}" } });
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(evaluation); });
  expect(screen.queryByRole("region", { name: label("calibration") })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: label("calculate") })).toBeDisabled();
});

it("supports explicit cancellation and aborts a subsequent request on unmount", async () => {
  let resolve!: (value: ResearchObject) => void;
  vi.mocked(api.forexRegime).mockImplementation(() => new Promise((done) => { resolve = done; }));
  const view = render(<ForexRegimeLab />); loadExample();
  fireEvent.click(screen.getByRole("button", { name: label("calculate") }));
  const first = vi.mocked(api.forexRegime).mock.calls[0][1]!;
  fireEvent.click(screen.getByRole("button", { name: label("cancel") }));
  expect(first.aborted).toBe(true);
  await act(async () => { resolve(evaluation); });
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: label("calculate") }));
  const second = vi.mocked(api.forexRegime).mock.calls[1][1]!;
  view.unmount(); expect(second.aborted).toBe(true);
});

it("bounds imports before reading and ignores a file that finishes after a manual edit", async () => {
  render(<ForexRegimeLab />);
  const large = new File(["x"], "large.json"), readLarge = vi.fn();
  Object.defineProperties(large, { size: { value: 1024 * 1024 + 1 }, text: { value: readLarge } });
  fireEvent.change(screen.getByLabelText(label("import")), { target: { files: [large] } });
  expect(readLarge).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent(label("invalid"));
  let complete!: (value: string) => void;
  const pending = new File(["fixture"], "pending.json");
  Object.defineProperty(pending, "text", { value: () => new Promise<string>((done) => { complete = done; }) });
  fireEvent.change(screen.getByLabelText(label("import")), { target: { files: [pending] } });
  fireEvent.change(screen.getByLabelText(label("input")), { target: { value: "{}" } });
  await act(async () => { complete(example); });
  expect(screen.getByLabelText(label("input"))).toHaveValue("{}");
  const valid = new File([example], "valid.json");
  Object.defineProperty(valid, "text", { value: async () => example });
  fireEvent.change(screen.getByLabelText(label("import")), { target: { files: [valid] } });
  await waitFor(() => expect(screen.getByRole("button", { name: label("calculate") })).toBeEnabled());
  expect(api.forexRegime).not.toHaveBeenCalled();
});

it("exports the exact request and returned page, and pages with the same declared dataset", async () => {
  const second: ResearchObject = { ...evaluation,
    timeline: [{ index: 2, available_at: "2025-01-01T03:00:00Z", phase: "training", normalized_slope: .2, regime: "unknown", reason: "training_only", dwell_remaining: 0 }],
    paging: { offset: 2, limit: 2, total: 96, returned: 1, next_offset: null } };
  vi.mocked(api.forexRegime).mockResolvedValueOnce(evaluation).mockResolvedValueOnce(second);
  let downloaded: Blob | undefined;
  const createObjectURL = vi.fn((blob: Blob) => { downloaded = blob; return "blob:fixture-regime"; });
  vi.stubGlobal("URL", class extends URL { static createObjectURL = createObjectURL; static revokeObjectURL = vi.fn(); });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  render(<ForexRegimeLab />); await replay();
  expect(screen.getByRole("button", { name: label("previous") })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: label("export") }));
  expect(click).toHaveBeenCalledOnce();
  expect(click.mock.instances[0]).toHaveProperty("download", "forex-regime-replay.json");
  expect(downloaded!.type).toBe("application/json");
  expect(JSON.parse(await readBlob(downloaded!))).toEqual({ schema_version: 1, export_scope: "request_and_one_returned_timeline_page", request: JSON.parse(example), result: evaluation });
  expect(api.forexRegime).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: label("next") }));
  await waitFor(() => expect(api.forexRegime).toHaveBeenLastCalledWith({ ...JSON.parse(example), offset: 2 }, expect.any(AbortSignal)));
  await screen.findByRole("rowheader", { name: "2" });
  expect(screen.getByRole("button", { name: label("next") })).toBeDisabled();
  expect(screen.getByRole("button", { name: label("previous") })).toBeEnabled();
});

it("reports a failed read without automatic retry or a fabricated timeline", async () => {
  vi.mocked(api.forexRegime).mockRejectedValue(new Error("Regime fixture unavailable"));
  render(<ForexRegimeLab />); loadExample();
  fireEvent.click(screen.getByRole("button", { name: label("calculate") }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Regime fixture unavailable");
  expect(api.forexRegime).toHaveBeenCalledOnce();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: label("export") })).not.toBeInTheDocument();
});
