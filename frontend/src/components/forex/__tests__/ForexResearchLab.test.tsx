import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import i18n from "@/i18n";
import { api } from "@/lib/api";
import { syntheticCostStressRequest, syntheticForexRequest, syntheticTradePathsRequest, type ForexExperimentDetail, type ForexExperimentRun, type ForexResearchResult } from "@/lib/forexResearch";
import { ForexResearchLab } from "../ForexResearchLab";

vi.mock("@/lib/api", () => ({ api: { forexWalkForward: vi.fn(), forexCostStress: vi.fn(), forexTradePaths: vi.fn(), saveForexExperiment: vi.fn(), saveForexCostStressExperiment: vi.fn(), saveForexTradePathsExperiment: vi.fn(), listForexExperiments: vi.fn(), getForexExperiment: vi.fn(), getForexExperimentRun: vi.fn() } }));
beforeAll(async () => { await i18n.changeLanguage("en"); });
beforeEach(() => { Object.values(api).forEach((method) => vi.mocked(method).mockReset()); });

const evaluation: ForexResearchResult = { status: "ok", strategy_variant: "ema_crossover_next_open_one_bar_v1", out_of_sample_metrics: { net_return: 0, trade_count: 2 },
  folds: [{ fold: 1, status: "ok", selected: { fast: 2, slow: 4 }, training: { outcome_available_at: "2025-01-07T00:00:00Z" }, out_of_sample: { signal_start: "2025-01-07T01:00:00Z", outcome_available_at: "2025-01-08T00:00:00Z" }, out_of_sample_metrics: { net_return: 0, trade_count: 2 }, trials: [{ status: "error", code: "NO_TRAIN_TRADES" }, { status: "ok" }] }] };
const history = { experiments: [{ id: "old-exp", created_at: "2025-01-01", attempt_count: 1 }], total: 1, offset: 0, limit: 10 };
const detail: ForexExperimentDetail = { id: "old-exp", created_at: "2025-01-01", attempt_count: 1, offset: 0, limit: 10, runs: [{ id: "old-run", attempt: 1, input_hash: "old-hash", status: "running", created_at: "2025-01-01", finished_at: null }] };
function saved(overrides: Partial<ForexExperimentRun> = {}): ForexExperimentRun {
  return { id: "new-run", experiment_id: "new-exp", attempt: 1, input_hash: "new-hash", status: "ok", created_at: "2025-01-02", finished_at: "2025-01-02", request: syntheticForexRequest(), engine: { python: "fixture", source_sha256: "fixture" }, result: evaluation, ...overrides };
}
async function calculate() {
  fireEvent.click(screen.getByText("Load synthetic example"));
  fireEvent.click(screen.getByRole("button", { name: i18n.t("forexLab.calculate") }));
  await screen.findByRole("region", { name: "Evaluation result" });
}

it("calculates without saving and displays zero OOS return plus all trial errors", async () => {
  vi.mocked(api.forexWalkForward).mockResolvedValue(evaluation);
  render(<ForexResearchLab />);
  expect(api.forexWalkForward).not.toHaveBeenCalled();
  await calculate();
  expect(screen.getByText(/not historical XAUUSD prices/)).toBeVisible();
  expect(screen.getByText("ema_crossover_next_open_one_bar_v1")).toBeVisible();
  expect(within(screen.getByRole("region", { name: "Evaluation result" })).getByRole("cell", { name: "0" })).toBeVisible();
  expect(screen.getByText(/NO_TRAIN_TRADES/)).toBeInTheDocument();
  expect(api.saveForexExperiment).not.toHaveBeenCalled();
  expect(api.forexWalkForward).toHaveBeenCalledWith(expect.objectContaining({ source: "synthetic_web_example_not_market_data", bars: expect.any(Array) }), expect.any(AbortSignal));
});

it("aborts a calculation when inputs change and ignores its late result", async () => {
  let resolve!: (result: ForexResearchResult) => void;
  vi.mocked(api.forexWalkForward).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<ForexResearchLab />);
  fireEvent.click(screen.getByText("Load synthetic example")); fireEvent.click(screen.getByRole("button", { name: i18n.t("forexLab.calculate") }));
  const signal = vi.mocked(api.forexWalkForward).mock.calls[0][1]!;
  fireEvent.change(screen.getByLabelText(/Research request JSON/), { target: { value: "{}" } });
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(evaluation); });
  expect(screen.queryByRole("region", { name: "Evaluation result" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: i18n.t("forexLab.calculate") })).toBeDisabled();
});

it("saves once on a separate action and a late detail read cannot overwrite its receipt", async () => {
  vi.mocked(api.forexWalkForward).mockResolvedValue(evaluation);
  vi.mocked(api.listForexExperiments).mockResolvedValue(history);
  vi.mocked(api.saveForexExperiment).mockResolvedValue(saved());
  let resolve!: (result: ForexExperimentDetail) => void;
  vi.mocked(api.getForexExperiment).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<ForexResearchLab />); await calculate();
  fireEvent.click(screen.getByText("Read / refresh history"));
  fireEvent.click(await screen.findByRole("button", { name: /old-exp/ }));
  const signal = vi.mocked(api.getForexExperiment).mock.calls[0][2]!;
  fireEvent.click(screen.getByText("Save a research attempt"));
  expect(await screen.findByText("Saved new-run with status ok.")).toBeVisible();
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(detail); });
  expect(screen.getByText("new-exp / new-run")).toBeVisible();
  expect(screen.queryByRole("heading", { name: "old-exp" })).not.toBeInTheDocument();
  expect(api.saveForexExperiment).toHaveBeenCalledOnce();
  expect(api.saveForexExperiment).toHaveBeenCalledWith(syntheticForexRequest(), undefined);
});

it("reports running attempts with an empty stored result as unknown", async () => {
  vi.mocked(api.listForexExperiments).mockResolvedValue(history);
  vi.mocked(api.getForexExperiment).mockResolvedValue(detail);
  vi.mocked(api.getForexExperimentRun).mockResolvedValue(saved({ id: "old-run", experiment_id: "old-exp", status: "running", result: {} as ForexResearchResult }));
  render(<ForexResearchLab />); fireEvent.click(screen.getByText("Read / refresh history"));
  fireEvent.click(await screen.findByRole("button", { name: /old-exp/ }));
  fireEvent.click(await screen.findByRole("button", { name: /old-run/ }));
  expect(await screen.findByText(/completion is unknown/)).toBeVisible();
  expect(screen.queryByRole("region", { name: "Evaluation result" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Load these inputs into editor"));
  expect(api.forexWalkForward).not.toHaveBeenCalled(); expect(api.saveForexExperiment).not.toHaveBeenCalled();
  expect(screen.getByLabelText(/Research request JSON/)).toHaveValue(JSON.stringify(syntheticForexRequest(), null, 2));
});

it("never automatically retries an uncertain save", async () => {
  vi.mocked(api.forexWalkForward).mockResolvedValue(evaluation);
  vi.mocked(api.saveForexExperiment).mockRejectedValue(new Error("Write outcome unknown"));
  render(<ForexResearchLab />); await calculate(); fireEvent.click(screen.getByText("Save a research attempt"));
  expect(await screen.findByRole("alert")).toHaveTextContent("check experiment history before submitting again");
  expect(api.saveForexExperiment).toHaveBeenCalledOnce(); expect(api.listForexExperiments).not.toHaveBeenCalled();
});

it("shows incomplete OOS explicitly and retains the failed folds", async () => {
  vi.mocked(api.forexWalkForward).mockResolvedValue({ ...evaluation, status: "incomplete", out_of_sample_metrics: null });
  render(<ForexResearchLab />); await calculate();
  expect(screen.getByText(/complete OOS aggregate is unavailable/)).toBeVisible();
  expect(screen.getByText("Save a research attempt")).toBeEnabled();
});

it("imports bounded files and rejects oversized uploads before reading", async () => {
  render(<ForexResearchLab />);
  const large = new File(["x"], "large.json"); Object.defineProperty(large, "size", { value: 1024 * 1024 + 1 });
  fireEvent.change(screen.getByLabelText("Import request JSON"), { target: { files: [large] } });
  expect(screen.getByRole("alert")).toHaveTextContent("exceeds 1 MB");
  const file = new File(["fixture"], "research.json"); Object.defineProperty(file, "text", { value: async () => JSON.stringify(syntheticForexRequest()) });
  fireEvent.change(screen.getByLabelText("Import request JSON"), { target: { files: [file] } });
  await waitFor(() => expect(screen.getByRole("button", { name: i18n.t("forexLab.calculate") })).toBeEnabled());
  expect(api.forexWalkForward).not.toHaveBeenCalled();
});

it("uses server pagination and ignores old history responses", async () => {
  vi.mocked(api.listForexExperiments).mockResolvedValue({ ...history, total: 11 });
  render(<ForexResearchLab />); fireEvent.click(screen.getByText("Read / refresh history"));
  await screen.findByText("11 experiments");
  fireEvent.click(screen.getByText("Next experiments"));
  await waitFor(() => expect(api.listForexExperiments).toHaveBeenLastCalledWith(10, expect.any(AbortSignal)));
});

const stressEvaluation: ForexResearchResult = {
  status: "incomplete", experiment_kind: "frozen_oos_cost_stress", frozen_oos_tape_hash: "a".repeat(64),
  base_walk_forward: evaluation,
  scenarios: [
    { spread_multiplier: 1, round_trip_cost_bps: 2, status: "ok", out_of_sample_metrics: {
      net_return: 0, net_expectancy_bps: -1.5, arithmetic_break_even_spread_bps: -1.75 } },
    { spread_multiplier: 2, round_trip_cost_bps: 3, status: "ok", out_of_sample_metrics: {
      net_return: -.02, net_expectancy_bps: -2.5, arithmetic_break_even_spread_bps: -1.75 } },
    { spread_multiplier: 3, round_trip_cost_bps: 4, status: "incomplete", out_of_sample_metrics: null },
  ],
};

function selectStress() {
  fireEvent.change(screen.getByRole("combobox", { name: i18n.t("forexLab.method") }), { target: { value: "cost_stress" } });
}

async function calculateStress() {
  selectStress();
  fireEvent.click(screen.getByRole("button", { name: i18n.t("forexLab.example") }));
  fireEvent.click(screen.getByRole("button", { name: i18n.t("forexLab.calculate") }));
  return screen.findByRole("region", { name: i18n.t("forexLab.stressResult") });
}

it("calculates an explicit synthetic stress request without saving and preserves negative and unknown results", async () => {
  vi.mocked(api.forexCostStress).mockResolvedValue(stressEvaluation);
  render(<ForexResearchLab />);
  expect(api.forexCostStress).not.toHaveBeenCalled();
  const region = await calculateStress();
  expect(screen.getByLabelText(/Research request JSON/)).toHaveValue(JSON.stringify(syntheticCostStressRequest(), null, 2));
  expect(api.forexCostStress).toHaveBeenCalledWith(syntheticCostStressRequest(), expect.any(AbortSignal));
  expect(api.forexWalkForward).not.toHaveBeenCalled();
  expect(api.saveForexExperiment).not.toHaveBeenCalled();
  expect(api.saveForexCostStressExperiment).not.toHaveBeenCalled();
  expect(within(region).getByText("a".repeat(64))).toBeVisible();
  const rows = within(region).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(3);
  expect(within(rows[0]).getByRole("rowheader", { name: "1" })).toBeVisible();
  expect(within(rows[0]).getByRole("cell", { name: "0" })).toBeVisible();
  expect(within(rows[0]).getByRole("cell", { name: "-1.5" })).toBeVisible();
  expect(within(rows[0]).getByRole("cell", { name: "-1.75" })).toBeVisible();
  expect(within(rows[1]).getByRole("cell", { name: "-0.02" })).toBeVisible();
  expect(within(rows[2]).getAllByRole("cell", { name: "Unknown" })).toHaveLength(3);
  expect(within(rows[2]).getByRole("cell", { name: "incomplete" })).toBeVisible();
});

it("saves a stress attempt only on a separate action through its own endpoint", async () => {
  vi.mocked(api.forexCostStress).mockResolvedValue(stressEvaluation);
  vi.mocked(api.saveForexCostStressExperiment).mockResolvedValue(saved({ request: syntheticCostStressRequest(), result: stressEvaluation, status: "incomplete" }));
  vi.mocked(api.listForexExperiments).mockResolvedValue(history);
  render(<ForexResearchLab />); await calculateStress();
  expect(api.saveForexCostStressExperiment).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Save a research attempt" }));
  expect(await screen.findByText("Saved new-run with status incomplete.")).toBeVisible();
  expect(api.saveForexCostStressExperiment).toHaveBeenCalledOnce();
  expect(api.saveForexCostStressExperiment).toHaveBeenCalledWith(syntheticCostStressRequest(), undefined);
  expect(api.saveForexExperiment).not.toHaveBeenCalled();
});

it("loads a saved stress request into its method without running or saving and can append an explicit attempt", async () => {
  vi.mocked(api.listForexExperiments).mockResolvedValue(history);
  vi.mocked(api.getForexExperiment).mockResolvedValue(detail);
  vi.mocked(api.getForexExperimentRun).mockResolvedValue(saved({ id: "old-run", experiment_id: "old-exp", request: syntheticCostStressRequest(), result: stressEvaluation, status: "incomplete" }));
  vi.mocked(api.forexCostStress).mockResolvedValue(stressEvaluation);
  vi.mocked(api.saveForexCostStressExperiment).mockResolvedValue(saved({ experiment_id: "old-exp", attempt: 2, request: syntheticCostStressRequest(), result: stressEvaluation, status: "incomplete" }));
  render(<ForexResearchLab />); fireEvent.click(screen.getByText("Read / refresh history"));
  fireEvent.click(await screen.findByRole("button", { name: /old-exp/ }));
  fireEvent.click(await screen.findByRole("button", { name: /old-run/ }));
  await screen.findByRole("region", { name: i18n.t("forexLab.stressResult") });
  fireEvent.click(screen.getByText("Load these inputs into editor"));
  expect(screen.getByRole("combobox", { name: i18n.t("forexLab.method") })).toHaveValue("cost_stress");
  expect(screen.getByLabelText(/Research request JSON/)).toHaveValue(JSON.stringify(syntheticCostStressRequest(), null, 2));
  expect(api.forexCostStress).not.toHaveBeenCalled();
  expect(api.saveForexCostStressExperiment).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: i18n.t("forexLab.calculate") }));
  await waitFor(() => expect(api.forexCostStress).toHaveBeenCalledOnce());
  fireEvent.click(await screen.findByRole("button", { name: "Save a research attempt" }));
  await waitFor(() => expect(api.saveForexCostStressExperiment).toHaveBeenCalledWith(syntheticCostStressRequest(), "old-exp"));
  expect(api.forexWalkForward).not.toHaveBeenCalled();
  expect(api.saveForexExperiment).not.toHaveBeenCalled();
});

it("aborts a pending stress evaluation when the method changes and ignores its late response", async () => {
  let resolve!: (result: ForexResearchResult) => void;
  vi.mocked(api.forexCostStress).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<ForexResearchLab />); selectStress();
  fireEvent.click(screen.getByText("Load synthetic example"));
  fireEvent.click(screen.getByRole("button", { name: i18n.t("forexLab.calculate") }));
  const signal = vi.mocked(api.forexCostStress).mock.calls[0][1]!;
  fireEvent.change(screen.getByRole("combobox", { name: i18n.t("forexLab.method") }), { target: { value: "walk_forward" } });
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(stressEvaluation); });
  expect(screen.queryByRole("region", { name: i18n.t("forexLab.stressResult") })).not.toBeInTheDocument();
  expect(screen.getByLabelText(/Research request JSON/)).toHaveValue("");
  expect(api.forexWalkForward).not.toHaveBeenCalled();
});

it("keeps stress editor controls locked during one uncertain save and never retries it", async () => {
  vi.mocked(api.forexCostStress).mockResolvedValue(stressEvaluation);
  let reject!: (reason: Error) => void;
  vi.mocked(api.saveForexCostStressExperiment).mockImplementation(() => new Promise((_, fail) => { reject = fail; }));
  render(<ForexResearchLab />); await calculateStress();
  fireEvent.click(screen.getByRole("button", { name: "Save a research attempt" }));
  expect(screen.getByRole("combobox", { name: i18n.t("forexLab.method") })).toBeDisabled();
  expect(screen.getByLabelText(/Research request JSON/)).toBeDisabled();
  await act(async () => { reject(new Error("Write outcome unknown")); });
  expect(await screen.findByRole("alert")).toHaveTextContent("check experiment history before submitting again");
  expect(api.saveForexCostStressExperiment).toHaveBeenCalledOnce();
  expect(api.listForexExperiments).not.toHaveBeenCalled();
});

it.each(["resolved", "rejected"])("ignores a pending file read that is %s after a stress save begins", async (outcome) => {
  const request = syntheticCostStressRequest();
  vi.mocked(api.forexCostStress).mockResolvedValue(stressEvaluation);
  vi.mocked(api.listForexExperiments).mockResolvedValue(history);
  let finishSave!: (run: ForexExperimentRun) => void;
  vi.mocked(api.saveForexCostStressExperiment).mockImplementation(() => new Promise((done) => { finishSave = done; }));
  render(<ForexResearchLab />); await calculateStress();

  let finishRead!: (text: string) => void;
  let failRead!: (error: Error) => void;
  const file = new File(["fixture"], "pending-stress.json");
  Object.defineProperty(file, "text", { value: () => new Promise<string>((done, fail) => { finishRead = done; failRead = fail; }) });
  fireEvent.change(screen.getByLabelText("Import request JSON"), { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "Save a research attempt" }));
  expect(api.saveForexCostStressExperiment).toHaveBeenCalledWith(request, undefined);
  expect(screen.getByLabelText(/Research request JSON/)).toBeDisabled();

  await act(async () => {
    if (outcome === "resolved") {
      finishRead(JSON.stringify({ ...request, research: { ...request.research, symbol: "EURUSD", dataset_revision: "obsolete-upload" } }));
    } else failRead(new Error("obsolete file read failed"));
  });
  expect(screen.getByLabelText(/Research request JSON/)).toHaveValue(JSON.stringify(request, null, 2));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: i18n.t("forexLab.stressResult") })).toBeVisible();

  await act(async () => { finishSave(saved({ request, result: stressEvaluation, status: "incomplete" })); });
  expect(await screen.findByText("Saved new-run with status incomplete.")).toBeVisible();
  expect(screen.getByLabelText(/Research request JSON/)).toHaveValue(JSON.stringify(request, null, 2));
  expect(screen.getByText("new-exp / new-run")).toBeVisible();
  expect(api.saveForexCostStressExperiment).toHaveBeenCalledOnce();
});

const pathsEvaluation: ForexResearchResult = {
  status: "ok", experiment_kind: "frozen_oos_moving_block_bootstrap", frozen_oos_tape_hash: "b".repeat(64),
  config: { seed: 42, simulations: 100, block_length: 2 }, base_walk_forward: evaluation,
  actual_path: { trade_count: 6, net_return: 0, max_drawdown: .2 },
  simulation_summary: { requested_simulations: 100, valid_simulations: 100, invalid_simulations: 0,
    terminal_net_return_quantiles: { p05: -.3, p25: -.2, p50: 0, p75: .1, p95: .2 },
    max_drawdown_quantiles: { p05: .1, p25: .15, p50: .2, p75: .3, p95: .4 } },
  display_paths: { steps: [0, 3, 6], actual: [1, .8, 1], bands: { p05: [1, .7, .7], p25: [1, .8, .8],
    p50: [1, 1, 1], p75: [1, 1.1, 1.1], p95: [1, 1.2, 1.2] }, samples: [[1, .9, 1.1]] },
};

async function calculatePaths() {
  fireEvent.change(screen.getByRole("combobox", { name: i18n.t("forexLab.method") }), { target: { value: "trade_paths" } });
  fireEvent.click(screen.getByText("Load synthetic example"));
  fireEvent.click(screen.getByRole("button", { name: i18n.t("forexLab.calculate") }));
  return screen.findByRole("region", { name: i18n.t("forexLab.pathsResult") });
}

it("calculates a seeded synthetic trade-path study separately and renders negative quantiles, zero and a labeled fan", async () => {
  vi.mocked(api.forexTradePaths).mockResolvedValue(pathsEvaluation);
  render(<ForexResearchLab />);
  const region = await calculatePaths();
  expect(api.forexTradePaths).toHaveBeenCalledWith(syntheticTradePathsRequest(), expect.any(AbortSignal));
  expect(api.forexWalkForward).not.toHaveBeenCalled();
  expect(api.forexCostStress).not.toHaveBeenCalled();
  expect(api.saveForexTradePathsExperiment).not.toHaveBeenCalled();
  expect(screen.getByLabelText(/Research request JSON/)).toHaveValue(JSON.stringify(syntheticTradePathsRequest(), null, 2));
  expect(within(region).getByText("b".repeat(64))).toBeVisible();
  const rows = within(region).getAllByRole("row");
  expect(within(rows[1]).getByRole("cell", { name: "-0.3" })).toBeVisible();
  expect(within(rows[3]).getByRole("cell", { name: "0" })).toBeVisible();
  expect(within(region).getByRole("img", { name: i18n.t("forexLab.pathsChart") })).toBeVisible();
});

it("requires an explicit action to save a trade-path study and preserves its request", async () => {
  vi.mocked(api.forexTradePaths).mockResolvedValue(pathsEvaluation);
  vi.mocked(api.saveForexTradePathsExperiment).mockResolvedValue(saved({ request: syntheticTradePathsRequest(), result: pathsEvaluation }));
  vi.mocked(api.listForexExperiments).mockResolvedValue(history);
  render(<ForexResearchLab />); await calculatePaths();
  fireEvent.click(screen.getByRole("button", { name: "Save a research attempt" }));
  expect(await screen.findByText("Saved new-run with status ok.")).toBeVisible();
  expect(api.saveForexTradePathsExperiment).toHaveBeenCalledOnce();
  expect(api.saveForexTradePathsExperiment).toHaveBeenCalledWith(syntheticTradePathsRequest(), undefined);
  expect(api.saveForexExperiment).not.toHaveBeenCalled();
  expect(api.saveForexCostStressExperiment).not.toHaveBeenCalled();
});

it("restores a saved trade-path method without confusing its nested research with cost stress", async () => {
  vi.mocked(api.listForexExperiments).mockResolvedValue(history);
  vi.mocked(api.getForexExperiment).mockResolvedValue(detail);
  vi.mocked(api.getForexExperimentRun).mockResolvedValue(saved({ id: "old-run", experiment_id: "old-exp", request: syntheticTradePathsRequest(), result: pathsEvaluation }));
  render(<ForexResearchLab />); fireEvent.click(screen.getByText("Read / refresh history"));
  fireEvent.click(await screen.findByRole("button", { name: /old-exp/ }));
  fireEvent.click(await screen.findByRole("button", { name: /old-run/ }));
  await screen.findByRole("region", { name: i18n.t("forexLab.pathsResult") });
  fireEvent.click(screen.getByText("Load these inputs into editor"));
  expect(screen.getByRole("combobox", { name: i18n.t("forexLab.method") })).toHaveValue("trade_paths");
  expect(screen.getByLabelText(/Research request JSON/)).toHaveValue(JSON.stringify(syntheticTradePathsRequest(), null, 2));
  expect(api.forexTradePaths).not.toHaveBeenCalled();
  expect(api.forexCostStress).not.toHaveBeenCalled();
  expect(api.saveForexTradePathsExperiment).not.toHaveBeenCalled();
});

it.each(["INSUFFICIENT_FOLD_TRADES", "SIMULATION_NUMERIC_FAILURE"])("keeps unavailable trade-path bands unknown for %s", async (code) => {
  vi.mocked(api.forexTradePaths).mockResolvedValue({ ...pathsEvaluation, status: "incomplete", code,
    simulation_summary: code === "SIMULATION_NUMERIC_FAILURE" ? { requested_simulations: 100, valid_simulations: 99,
      invalid_simulations: 1, terminal_net_return_quantiles: null, max_drawdown_quantiles: null } : null,
    display_paths: null });
  render(<ForexResearchLab />);
  const region = await calculatePaths();
  expect(within(region).getByText(new RegExp(code), { selector: "p" })).toBeVisible();
  expect(within(region).getAllByRole("cell", { name: "Unknown" })).toHaveLength(10);
  expect(within(region).queryByRole("img")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save a research attempt" })).toBeEnabled();
});

it("aborts trade-path reads and suppresses stale bands when the method changes", async () => {
  let resolve!: (result: ForexResearchResult) => void;
  vi.mocked(api.forexTradePaths).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<ForexResearchLab />);
  fireEvent.change(screen.getByRole("combobox", { name: i18n.t("forexLab.method") }), { target: { value: "trade_paths" } });
  fireEvent.click(screen.getByText("Load synthetic example"));
  fireEvent.click(screen.getByRole("button", { name: i18n.t("forexLab.calculate") }));
  const signal = vi.mocked(api.forexTradePaths).mock.calls[0][1]!;
  selectStress();
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(pathsEvaluation); });
  expect(screen.queryByRole("region", { name: i18n.t("forexLab.pathsResult") })).not.toBeInTheDocument();
  expect(screen.getByLabelText(/Research request JSON/)).toHaveValue("");
});

it.each(["success", "error"])("signals a pending trade-path write to its parent and unlocks after %s", async (outcome) => {
  const onBusyChange = vi.fn();
  vi.mocked(api.forexTradePaths).mockResolvedValue(pathsEvaluation);
  vi.mocked(api.listForexExperiments).mockResolvedValue(history);
  let complete!: (run: ForexExperimentRun) => void;
  let fail!: (error: Error) => void;
  vi.mocked(api.saveForexTradePathsExperiment).mockImplementation(() => new Promise((done, reject) => { complete = done; fail = reject; }));
  render(<ForexResearchLab onBusyChange={onBusyChange} />); await calculatePaths();
  expect(onBusyChange).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Save a research attempt" }));
  expect(onBusyChange).toHaveBeenLastCalledWith(true);
  await act(async () => {
    if (outcome === "success") complete(saved({ request: syntheticTradePathsRequest(), result: pathsEvaluation }));
    else fail(new Error("uncertain write"));
  });
  expect(onBusyChange.mock.calls).toEqual([[true], [false]]);
});
