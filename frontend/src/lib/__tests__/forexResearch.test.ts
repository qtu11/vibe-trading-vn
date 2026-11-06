import { api } from "../api";
import { MAX_RESEARCH_BYTES, forexLabMethod, parseForexLab, parseForexCostStress, parseForexResearch, parseForexTradePaths, syntheticCostStressRequest, syntheticForexRequest, syntheticTradePathsRequest } from "../forexResearch";

it("provides a deterministic, explicitly synthetic contiguous closed-bar request", () => {
  const request = syntheticForexRequest();
  expect(parseForexResearch(JSON.stringify(request))).toEqual(request);
  expect(request.source).toContain("synthetic");
  expect(request.bars).toHaveLength(96);
  expect(request.bars.every((bar) => bar.complete === true)).toBe(true);
  expect(new Date(String(request.bars[1].time)).getTime() - new Date(String(request.bars[0].time)).getTime()).toBe(3600000);
});

it.each(["null", "[]", "{}", "not JSON", JSON.stringify({ ...syntheticForexRequest(), bars: [] }), JSON.stringify({ ...syntheticForexRequest(), round_trip_cost_bps: "2" })])("rejects malformed or unbounded preview inputs: %s", (text) => {
  expect(() => parseForexResearch(text)).toThrow();
});

it("counts UTF-8 bytes instead of accepting oversized multibyte JSON", () => {
  const request = syntheticForexRequest(); request.source = "中".repeat(MAX_RESEARCH_BYTES / 2);
  expect(() => parseForexResearch(JSON.stringify(request))).toThrow("too_large");
});

it("provides explicit deterministic round-trip components for a synthetic mid-bar stress study", () => {
  const request = syntheticCostStressRequest();
  expect(parseForexCostStress(JSON.stringify(request))).toEqual(request);
  expect(request).toEqual({ research: syntheticForexRequest(), spread_bps: 1, commission_bps: .5, slippage_bps: .5, gap_bps: 0 });
  expect(request.research.price_basis).toBe("mid");
  expect(request.research.source).toContain("synthetic");
  expect(request.spread_bps + request.commission_bps + request.slippage_bps + request.gap_bps).toBe(request.research.round_trip_cost_bps);
  expect(request).toEqual(syntheticCostStressRequest());
});

it.each(["spread_bps", "commission_bps", "slippage_bps", "gap_bps"])("requires an explicit finite nonnegative numeric %s in the preview", (field) => {
  for (const invalid of [undefined, null, true, "1", -1, Number.POSITIVE_INFINITY]) {
    const request = { ...syntheticCostStressRequest(), [field]: invalid };
    expect(() => parseForexCostStress(JSON.stringify(request))).toThrow("request_shape");
  }
});

it.each(["null", "[]", "{}", "not JSON", JSON.stringify({ ...syntheticCostStressRequest(), research: [] }),
  JSON.stringify({ ...syntheticCostStressRequest(), research: { ...syntheticForexRequest(), bars: [] } })])("rejects malformed nested stress inputs: %s", (text) => {
  expect(() => parseForexCostStress(text)).toThrow();
});

it("preserves explicit zero stress costs and defers full strategy validation to the server", () => {
  const request = { ...syntheticCostStressRequest(), spread_bps: 0, commission_bps: 0, slippage_bps: 0, gap_bps: 0,
    research: { ...syntheticForexRequest(), round_trip_cost_bps: 0 } };
  expect(parseForexCostStress(JSON.stringify(request))).toEqual(request);
});

it("applies the UTF-8 byte budget to the whole nested stress request", () => {
  const request = syntheticCostStressRequest();
  request.research.source = "中".repeat(MAX_RESEARCH_BYTES / 2);
  expect(() => parseForexCostStress(JSON.stringify(request))).toThrow("too_large");
});

it("roundtrips a clearly synthetic seeded trade-path request and recognizes every saved method", () => {
  const request = syntheticTradePathsRequest();
  expect(request.research.source).toContain("synthetic");
  expect(request.seed).toBe(42);
  expect(request.simulations).toBe(100);
  expect(request.block_length).toBe(2);
  expect(parseForexTradePaths(JSON.stringify(request))).toEqual(request);
  expect(parseForexLab(JSON.stringify(request), "trade_paths")).toEqual(request);
  expect(forexLabMethod(request)).toBe("trade_paths");
  expect(forexLabMethod(syntheticCostStressRequest())).toBe("cost_stress");
  expect(forexLabMethod(syntheticForexRequest())).toBe("walk_forward");
});

it.each([
  ["seed", true], ["seed", -1], ["seed", "42"], ["seed", 4294967296], ["seed", 1.5],
  ["simulations", 99], ["simulations", 2001], ["simulations", 100.5], ["simulations", null],
  ["block_length", 1], ["block_length", 65], ["block_length", "2"],
])("rejects malformed or unbounded trade-path %s=%s", (field, invalid) => {
  expect(() => parseForexTradePaths(JSON.stringify({ ...syntheticTradePathsRequest(), [String(field)]: invalid }))).toThrow("request_shape");
});

it("enforces nested trade-path inputs and the complete UTF-8 byte budget", () => {
  expect(() => parseForexTradePaths("{}")).toThrow();
  expect(() => parseForexTradePaths("null")).toThrow("request_object");
  expect(() => parseForexTradePaths("[]")).toThrow("request_object");
  const request = syntheticTradePathsRequest(); request.research.source = "中".repeat(MAX_RESEARCH_BYTES / 2);
  expect(() => parseForexTradePaths(JSON.stringify(request))).toThrow("too_large");
});

describe("cost stress and trade path API endpoints", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  function responseFetch() {
    const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ status: "ok" }), {
      headers: { "content-type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("localStorage", { getItem: vi.fn(() => "fixture-key"), setItem: vi.fn(), removeItem: vi.fn() });
    return fetch;
  }

  it("posts the nested request through the authenticated pure evaluation endpoint", async () => {
    const fetch = responseFetch();
    const request = syntheticCostStressRequest();
    await expect(api.forexCostStress(request, new AbortController().signal)).resolves.toEqual({ status: "ok" });
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledWith("/api/forex/cost-stress", expect.objectContaining({
      method: "POST", headers: expect.objectContaining({ Authorization: "Bearer fixture-key" }),
      body: JSON.stringify(request), signal: expect.any(AbortSignal),
    }));
  });

  it("keeps new and appended stress saves on explicit distinct journal routes", async () => {
    const fetch = responseFetch();
    const request = syntheticCostStressRequest();
    await api.saveForexCostStressExperiment(request);
    await api.saveForexCostStressExperiment(request, "experiment / fixture");
    expect(fetch).toHaveBeenNthCalledWith(1, "/api/forex/cost-stress/experiments", expect.objectContaining({ method: "POST", body: JSON.stringify(request) }));
    expect(fetch).toHaveBeenNthCalledWith(2, "/api/forex/cost-stress/experiments/experiment%20%2F%20fixture/runs", expect.objectContaining({ method: "POST", body: JSON.stringify(request) }));
  });

  it("does not replay a stress journal write after a connection failure", async () => {
    const fetch = responseFetch().mockRejectedValue(new TypeError("fixture connection failed"));
    await expect(api.saveForexCostStressExperiment(syntheticCostStressRequest())).rejects.toMatchObject({ code: "network_error" });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("posts a bounded seeded request to the authenticated pure trade-path endpoint", async () => {
    const fetch = responseFetch();
    const request = syntheticTradePathsRequest();
    await api.forexTradePaths(request, new AbortController().signal);
    expect(fetch).toHaveBeenCalledWith("/api/forex/trade-paths", expect.objectContaining({
      method: "POST", body: JSON.stringify(request), signal: expect.any(AbortSignal),
      headers: expect.objectContaining({ Authorization: "Bearer fixture-key" }),
    }));
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("uses explicit new and appended trade-path journal routes without replaying failed writes", async () => {
    const fetch = responseFetch();
    const request = syntheticTradePathsRequest();
    await api.saveForexTradePathsExperiment(request);
    await api.saveForexTradePathsExperiment(request, "example / existing");
    expect(fetch).toHaveBeenNthCalledWith(1, "/api/forex/trade-paths/experiments", expect.objectContaining({ method: "POST", body: JSON.stringify(request) }));
    expect(fetch).toHaveBeenNthCalledWith(2, "/api/forex/trade-paths/experiments/example%20%2F%20existing/runs", expect.objectContaining({ method: "POST", body: JSON.stringify(request) }));
    fetch.mockRejectedValue(new TypeError("fixture connection failed"));
    await expect(api.saveForexTradePathsExperiment(request)).rejects.toMatchObject({ code: "network_error" });
    expect(fetch).toHaveBeenCalledTimes(3);
  });
});
