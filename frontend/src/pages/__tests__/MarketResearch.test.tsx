import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18n from "@/i18n";
import { api } from "@/lib/api";
import type { ResearchResult } from "@/lib/research";
import { MarketResearch } from "../MarketResearch";

vi.mock("@/lib/api", () => ({ api: { researchVietnam: vi.fn(), researchCrypto: vi.fn(), captureCrypto: vi.fn(), saveResearchRevision: vi.fn(), forexRegime: vi.fn(), forexWalkForward: vi.fn() } }));
beforeAll(async () => { await i18n.changeLanguage("en"); });
beforeEach(() => { Object.values(api).forEach((method) => vi.mocked(method).mockReset()); });

function result(overrides: Partial<ResearchResult> = {}): ResearchResult {
  return { ok: true, data: { "CASE.VN": { venue: "HOSE", as_of: "2025-08-01T00:00:00+00:00", verification_status: "user_supplied_unverified", source_file_sha256: "a".repeat(64),
    periods: [{ period_start: "2025-04-01", period_end: "2025-06-30", checks: { balance_sheet: "passed" },
      metrics: { zero_residual: { value: "0", unit: "VND", reason: null }, missing_ratio: { value: null, unit: "ratio", reason: "missing_fact" } },
      inputs: {}, evidence: [{ id: "S1", source_url: "https://example.com/filing", locator: "Page 2", revision: "initial", document_sha256: "b".repeat(64) }] }] } },
    paging: { total: 2, offset: 0, returned: 1, next_offset: 1, complete: false }, ...overrides };
}

function chooseVn() { fireEvent.change(screen.getByLabelText("Configured listing (.VN)"), { target: { value: "case.vn" } }); }

it("waits for a deliberate request and preserves exact financial zero and unknown reasons", async () => {
  vi.mocked(api.researchVietnam).mockResolvedValue(result());
  render(<MarketResearch />);
  expect(api.researchVietnam).not.toHaveBeenCalled();
  chooseVn(); fireEvent.click(screen.getByRole("button", { name: "Run research" }));
  expect(await screen.findByText("CASE.VN · HOSE")).toBeVisible();
  expect(screen.getByRole("cell", { name: "0" })).toBeVisible();
  expect(screen.getByRole("cell", { name: "Unknown" })).toBeVisible();
  expect(screen.getByText("missing_fact")).toBeVisible();
  expect(screen.getByText(/not independently verified/)).toBeVisible();
  expect(api.researchVietnam).toHaveBeenCalledWith(expect.objectContaining({ code: "CASE.VN", offset: 0, as_of: undefined }), expect.any(AbortSignal));
});

it("makes reverse DCF and the crypto basis lab reachable without automatic research calls", () => {
  render(<MarketResearch />);
  fireEvent.change(screen.getByLabelText(i18n.t("valuationLab.workflow")), { target: { value: "reverse_dcf" } });
  expect(screen.getByRole("heading", { name: i18n.t("reverseDCF.title") })).toBeVisible();
  expect(screen.queryByLabelText("Configured listing (.VN)")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Market"), { target: { value: "crypto" } });
  fireEvent.change(screen.getByLabelText(i18n.t("cryptoBasis.workflow")), { target: { value: "basis" } });
  expect(screen.getByRole("heading", { name: i18n.t("cryptoBasis.title") })).toBeVisible();
  expect(screen.queryByLabelText("Perpetual symbol")).not.toBeInTheDocument();
  expect(api.researchVietnam).not.toHaveBeenCalled();
  expect(api.researchCrypto).not.toHaveBeenCalled();
  expect(api.saveResearchRevision).not.toHaveBeenCalled();
});

it("freezes the returned availability cutoff for the next reporting page", async () => {
  vi.mocked(api.researchVietnam).mockResolvedValue(result());
  render(<MarketResearch />); chooseVn(); fireEvent.click(screen.getByText("Run research"));
  fireEvent.click(await screen.findByText("Next reporting periods"));
  await waitFor(() => expect(api.researchVietnam).toHaveBeenLastCalledWith(expect.objectContaining({ as_of: "2025-08-01T00:00:00+00:00", offset: 1 }), expect.any(AbortSignal)));
});

it("keeps the reporting page and query fixed while saving a revision", async () => {
  vi.mocked(api.researchVietnam).mockResolvedValue(result());
  let reject!: (reason: Error) => void;
  vi.mocked(api.saveResearchRevision).mockImplementation(() => new Promise((_, fail) => { reject = fail; }));
  render(<MarketResearch />); chooseVn(); fireEvent.click(screen.getByText("Run research"));
  await screen.findByText("CASE.VN · HOSE");
  fireEvent.click(screen.getByRole("button", { name: i18n.t("researchRevision.save") }));
  expect(screen.getByRole("button", { name: "Next reporting periods" })).toBeDisabled();
  expect(screen.getByLabelText("Configured listing (.VN)")).toBeDisabled();
  expect(screen.getByLabelText("Market")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Next reporting periods" }));
  expect(api.researchVietnam).toHaveBeenCalledTimes(1);
  expect(api.saveResearchRevision).toHaveBeenCalledWith("vietnam", expect.objectContaining({ code: "CASE.VN", offset: 0, as_of: "2025-08-01T00:00:00+00:00" }), undefined, expect.stringMatching(/^rk_[0-9a-f]{32}$/));
  await act(async () => { reject(new Error("uncertain write")); });
  expect(screen.getByRole("button", { name: "Next reporting periods" })).toBeEnabled();
  expect(screen.getByRole("alert")).toHaveTextContent("uncertain write");
  expect(api.saveResearchRevision).toHaveBeenCalledTimes(1);
});

it("aborts and ignores a late result after the query changes", async () => {
  let resolve!: (value: ResearchResult) => void;
  vi.mocked(api.researchVietnam).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<MarketResearch />); chooseVn(); fireEvent.click(screen.getByText("Run research"));
  const signal = vi.mocked(api.researchVietnam).mock.calls[0][1]!;
  fireEvent.change(screen.getByLabelText("Configured listing (.VN)"), { target: { value: "NEXT.VN" } });
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(result()); });
  expect(screen.queryByText("CASE.VN · HOSE")).not.toBeInTheDocument();
});

it("cancels on unmount and exposes an explicit cancel request action", async () => {
  vi.mocked(api.researchVietnam).mockReturnValue(new Promise(() => {}));
  const { unmount } = render(<MarketResearch />); chooseVn(); fireEvent.click(screen.getByText("Run research"));
  const first = vi.mocked(api.researchVietnam).mock.calls[0][1]!;
  fireEvent.click(screen.getByText("Cancel request")); expect(first.aborted).toBe(true);
  fireEvent.click(screen.getByText("Run research"));
  const second = vi.mocked(api.researchVietnam).mock.calls[1][1]!;
  unmount(); expect(second.aborted).toBe(true);
});

it("shows tool failures without rendering a successful data panel", async () => {
  vi.mocked(api.researchVietnam).mockResolvedValue({ ok: false, error: "Configured source missing" });
  render(<MarketResearch />); chooseVn(); fireEvent.click(screen.getByText("Run research"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Configured source missing");
  expect(screen.queryByText("CASE.VN · HOSE")).not.toBeInTheDocument();
});

it("renders crypto coverage/null and disables OI-only sampling for funding", async () => {
  vi.mocked(api.researchCrypto).mockResolvedValue({ ok: true, symbol: "BTC-USDT-PERP", metric: "funding", summary: { realized_events: 2, long_cash_per_base_quote: null }, coverage: { unique_records: 2, completeness: "unknown" }, provenance: { historical_available_at: null }, observations: [] });
  render(<MarketResearch />);
  fireEvent.change(screen.getByLabelText("Market"), { target: { value: "crypto" } });
  expect(api.researchCrypto).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Perpetual symbol"), { target: { value: "btc-usdt-perp" } });
  fireEvent.change(screen.getByLabelText("Metric"), { target: { value: "funding" } });
  expect(screen.getByLabelText("OI sampling interval")).toBeDisabled();
  fireEvent.click(screen.getByText("Run research"));
  expect(await screen.findByText("BTC-USDT-PERP · funding")).toBeVisible();
  expect(screen.getByText(/Historical availability and completeness are unknown/)).toBeVisible();
  expect(screen.getAllByRole("cell", { name: "Unknown" }).length).toBeGreaterThan(0);
  expect(api.researchCrypto).toHaveBeenCalledWith(expect.objectContaining({ symbol: "BTC-USDT-PERP", metric: "funding", limit: 30 }), expect.any(AbortSignal));
});

it("blocks unsafe evidence anchors and preserves safe filing links", async () => {
  const unsafe = result();
  const periods = unsafe.data!["CASE.VN"].periods as unknown as { evidence: { source_url: string }[] }[];
  periods[0].evidence.push({ source_url: "javascript:alert(1)" });
  vi.mocked(api.researchVietnam).mockResolvedValue(unsafe);
  render(<MarketResearch />); chooseVn(); fireEvent.click(screen.getByText("Run research"));
  const link = await screen.findByRole("link", { hidden: true, name: "https://example.com/filing" });
  expect(link).toHaveAttribute("href", "https://example.com/filing");
  expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
});

it("clears old results when the market changes and reports transport errors", async () => {
  vi.mocked(api.researchVietnam).mockResolvedValue(result());
  vi.mocked(api.researchCrypto).mockRejectedValue(new Error("API connection failed"));
  render(<MarketResearch />); chooseVn(); fireEvent.click(screen.getByText("Run research"));
  await screen.findByText("CASE.VN · HOSE");
  fireEvent.change(screen.getByLabelText("Market"), { target: { value: "crypto" } });
  expect(screen.queryByText("CASE.VN · HOSE")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Perpetual symbol"), { target: { value: "BTC-USDT-PERP" } });
  fireEvent.click(screen.getByText("Run research"));
  expect(await screen.findByRole("alert")).toHaveTextContent("API connection failed");
});

it("explains invalid listing and timezone before making a request", () => {
  render(<MarketResearch />);
  fireEvent.change(screen.getByLabelText("Configured listing (.VN)"), { target: { value: "FPT" } });
  fireEvent.click(screen.getByText("Run research"));
  expect(screen.getByRole("alert")).toHaveTextContent("ending in .VN");
  chooseVn();
  fireEvent.change(screen.getByLabelText(/Availability cutoff/), { target: { value: "2025-08-01" } });
  fireEvent.click(screen.getByText("Run research"));
  expect(screen.getByRole("alert")).toHaveTextContent("ISO timestamp with timezone");
  expect(api.researchVietnam).not.toHaveBeenCalled();
});

it("requires an explicit perpetual product before contacting the provider", () => {
  render(<MarketResearch />);
  fireEvent.change(screen.getByLabelText("Market"), { target: { value: "crypto" } });
  fireEvent.change(screen.getByLabelText("Perpetual symbol"), { target: { value: "BTC-USDT" } });
  fireEvent.click(screen.getByText("Run research"));
  expect(screen.getByRole("alert")).toHaveTextContent("BTC-USDT-PERP");
  expect(api.researchCrypto).not.toHaveBeenCalled();
});

it("queries only the chosen local archive cutoff without automatically capturing", async () => {
  vi.mocked(api.researchCrypto).mockResolvedValue({ ok: false, error: "Archive not configured" });
  render(<MarketResearch />);
  fireEvent.change(screen.getByLabelText("Market"), { target: { value: "crypto" } });
  fireEvent.change(screen.getByLabelText("Perpetual symbol"), { target: { value: "BTC-USDT-PERP" } });
  fireEvent.change(screen.getByLabelText("History source"), { target: { value: "archive" } });
  fireEvent.change(screen.getByLabelText(/Local recording cutoff/), { target: { value: "2026-11-05T00:00:00Z" } });
  fireEvent.click(screen.getByText("Run research"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Archive not configured");
  expect(api.researchCrypto).toHaveBeenCalledWith(expect.objectContaining({ mode: "archive", as_of: "2026-11-05T00:00:00Z" }), expect.any(AbortSignal));
  expect(api.captureCrypto).not.toHaveBeenCalled();
  expect(screen.queryByText("Fetch and save a new capture")).not.toBeInTheDocument();
});

it("captures only by explicit action and displays the local receipt", async () => {
  vi.mocked(api.captureCrypto).mockResolvedValue({ ok: true, symbol: "BTC-USDT-PERP", metric: "open_interest", archive: { capture_id: "fixture-capture-id", recorded_at: "2026-11-05T00:00:00Z" } });
  render(<MarketResearch />);
  fireEvent.change(screen.getByLabelText("Market"), { target: { value: "crypto" } });
  fireEvent.change(screen.getByLabelText("Perpetual symbol"), { target: { value: "BTC-USDT-PERP" } });
  expect(api.captureCrypto).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Fetch and save a new capture"));
  expect(await screen.findByText("fixture-capture-id")).toBeVisible();
  expect(api.captureCrypto).toHaveBeenCalledOnce();
  expect(api.captureCrypto).toHaveBeenCalledWith({ symbol: "BTC-USDT-PERP", metric: "open_interest", period: "1h", limit: 30 });
  expect(api.researchCrypto).not.toHaveBeenCalled();
});

it("does not retry a failed capture or claim it was saved", async () => {
  vi.mocked(api.captureCrypto).mockRejectedValue(new Error("Write timeout"));
  render(<MarketResearch />);
  fireEvent.change(screen.getByLabelText("Market"), { target: { value: "crypto" } });
  fireEvent.change(screen.getByLabelText("Perpetual symbol"), { target: { value: "BTC-USDT-PERP" } });
  fireEvent.click(screen.getByText("Fetch and save a new capture"));
  expect(await screen.findByRole("alert")).toHaveTextContent("save outcome is uncertain");
  expect(api.captureCrypto).toHaveBeenCalledOnce();
  expect(screen.queryByText("Local archive receipt and revision policy")).not.toBeInTheDocument();
});

it("makes the Forex lab reachable from the same market selector", () => {
  render(<MarketResearch />);
  fireEvent.change(screen.getByLabelText("Market"), { target: { value: "forex" } });
  expect(screen.getByRole("region", { name: "Forex research lab" })).toBeVisible();
  expect(screen.getByText("Load synthetic example")).toBeVisible();
  expect(api.researchVietnam).not.toHaveBeenCalled();
  expect(screen.getByLabelText(i18n.t("forexRegime.workflow"))).toHaveValue("lab");
  expect(api.forexRegime).not.toHaveBeenCalled();
});

it("switches Forex workflows deliberately and aborts a late regime response", async () => {
  let resolve!: (value: Record<string, never>) => void;
  vi.mocked(api.forexRegime).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<MarketResearch />);
  fireEvent.change(screen.getByLabelText("Market"), { target: { value: "forex" } });
  fireEvent.change(screen.getByLabelText(i18n.t("forexRegime.workflow")), { target: { value: "regime" } });
  expect(screen.getByRole("region", { name: i18n.t("forexRegime.title") })).toBeVisible();
  expect(screen.queryByRole("region", { name: "Forex research lab" })).not.toBeInTheDocument();
  expect(api.forexRegime).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: i18n.t("forexRegime.example") }));
  fireEvent.click(screen.getByRole("button", { name: i18n.t("forexRegime.calculate") }));
  const signal = vi.mocked(api.forexRegime).mock.calls[0][1]!;
  fireEvent.change(screen.getByLabelText(i18n.t("forexRegime.workflow")), { target: { value: "lab" } });
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve({}); });
  expect(screen.getByRole("region", { name: "Forex research lab" })).toBeVisible();
  expect(screen.queryByRole("region", { name: i18n.t("forexRegime.title") })).not.toBeInTheDocument();
  expect(api.forexWalkForward).not.toHaveBeenCalled();
});
