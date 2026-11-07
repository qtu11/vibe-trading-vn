import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";

async function loadApiModule() {
  vi.resetModules();
  return import("../api");
}

describe("generated report download", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
  it("downloads PDF bytes with bearer authentication and keeps the key out of the URL", async () => {
    vi.stubGlobal("localStorage", { getItem: vi.fn((key) => key === "vibe_trading_api_auth_key" ? "report-test-key" : "en"), setItem: vi.fn(), removeItem: vi.fn() });
    const fetch = vi.fn().mockResolvedValue(new Response("%PDF-contents", { headers: { "content-type": "application/pdf" } }));
    vi.stubGlobal("fetch", fetch);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.stubGlobal("URL", class extends URL {
      static createObjectURL = vi.fn(() => "blob:report");
      static revokeObjectURL = vi.fn();
    });
    const { downloadGeneratedReport } = await loadApiModule();
    await downloadGeneratedReport("a".repeat(32), "研究报告.pdf");
    expect(fetch).toHaveBeenCalledWith(`/api/reports/${"a".repeat(32)}`, expect.objectContaining({ headers: { Authorization: "Bearer report-test-key" } }));
    expect(click).toHaveBeenCalledOnce();
  });
  it("rejects invalid handles, unexpected MIME, oversized files and non-PDF bodies", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response("<html>login</html>", { headers: { "content-type": "text/html" } }))
      .mockResolvedValueOnce(new Response("%PDF-test", { headers: { "content-type": "application/pdf", "content-length": String(33 * 1024 * 1024) } }))
      .mockResolvedValueOnce(new Response("not a PDF", { headers: { "content-type": "application/pdf" } }));
    vi.stubGlobal("fetch", fetch);
    const { downloadGeneratedReport } = await loadApiModule();
    await expect(downloadGeneratedReport("../private", "report.pdf")).rejects.toThrow("Mã tài liệu");
    await expect(downloadGeneratedReport("a".repeat(32), "../report.pdf")).rejects.toThrow("Tên tài liệu");
    for (let index = 0; index < 3; index++) await expect(downloadGeneratedReport("a".repeat(32), "report.pdf")).rejects.toThrow(/tài liệu/);
    expect(fetch).toHaveBeenCalledTimes(3);
  });
  it("authenticates preview pages and rejects invalid PNG bytes or page handles", async () => {
    vi.stubGlobal("localStorage", { getItem: () => "preview-key", setItem: vi.fn(), removeItem: vi.fn() });
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(new Uint8Array([137,80,78,71,13,10,26,10,0]), { headers: { "content-type": "image/png" } }))
      .mockResolvedValueOnce(new Response("not-png", { headers: { "content-type": "image/png" } }));
    vi.stubGlobal("fetch", fetch);
    const { fetchReportPreviewPage } = await loadApiModule();
    const controller = new AbortController();
    await expect(fetchReportPreviewPage("a".repeat(32), 0, controller.signal)).resolves.toHaveProperty("size", 9);
    expect(fetch.mock.calls[0][0]).toBe(`/api/reports/${"a".repeat(32)}/preview/0`);
    expect(fetch.mock.calls[0][1]).toMatchObject({ headers: { Authorization: "Bearer preview-key" }, signal: expect.any(AbortSignal) });
    await expect(fetchReportPreviewPage("a".repeat(32), 1)).rejects.toThrow("Ảnh xem trước");
    await expect(fetchReportPreviewPage("a".repeat(32), -1)).rejects.toThrow("Trang xem trước");
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("validates the authenticated preview page count", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ pages: 2001 }), { headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    const { api } = await loadApiModule();
    await expect(api.getReportPreviewPages("a".repeat(32))).rejects.toThrow("Số trang xem trước");
  });
  it("looks up the owning job by fixed artifact route and rejects another job's receipt", async () => {
    const artifactId = "b".repeat(32);
    const job = { job_id: "a".repeat(32), status: "succeeded", formats: ["pdf"], error: null,
      artifacts: [{ report_id: artifactId, download_url: `/api/reports/${artifactId}`, filename: "research.pdf", media_type: "application/pdf", sha256: "c".repeat(64), size_bytes: 1000 }],
      publication_status: "draft_unverified", created_at: "2026-11-07", updated_at: "2026-11-07" };
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(job), { headers: { "content-type": "application/json" } })));
    vi.stubGlobal("fetch", fetch);
    const { api } = await loadApiModule();
    await expect(api.getReportJobForArtifact(artifactId)).resolves.toEqual(job);
    expect(fetch.mock.calls[0][0]).toBe(`/api/reports/artifacts/${artifactId}/job`);
    await expect(api.getReportJobForArtifact("d".repeat(32))).rejects.toThrow("Dữ liệu báo cáo");
    await expect(api.getReportJobForArtifact("bad/id")).rejects.toThrow("Mã tài liệu");
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});

describe("api request helper", () => {
  it("keeps an explicit calculation key in the authenticated body and reads filtered receipts", async () => {
    vi.stubGlobal("localStorage", { getItem: () => "research-key", setItem: vi.fn(), removeItem: vi.fn() });
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { headers: { "content-type": "application/json" } })));
    vi.stubGlobal("fetch", fetch);
    const { api } = await loadApiModule();
    await api.saveResearchRevision("vietnam_dcf", { symbol: "CASE.VN" }, "rr_parent", "rk_explicit_intent");
    await api.listResearchAttempts("vietnam_dcf", "rr_parent", "rk_explicit_intent", 10);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ kind: "vietnam_dcf", request: { symbol: "CASE.VN" }, parent_revision_id: "rr_parent", idempotency_key: "rk_explicit_intent" });
    expect(fetch.mock.calls[1][0]).toBe("/api/research/artifacts/attempts?kind=vietnam_dcf&parent_revision_id=rr_parent&idempotency_key=rk_explicit_intent&limit=10&offset=10");
    for (const [, init] of fetch.mock.calls) expect(init.headers).toMatchObject({ Authorization: "Bearer research-key" });
  });
  it("reads exact authenticated Markdown and rejects HTML or an oversized UTF-8 report", async () => {
    vi.stubGlobal("localStorage", { getItem: () => "report-key", setItem: vi.fn(), removeItem: vi.fn() });
    const markdown = "# Nghiên cứu\n\nGiá trị: chưa xác minh.\n";
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(markdown, { headers: { "content-type": "text/markdown; charset=utf-8" } }))
      .mockResolvedValueOnce(new Response("<html>login</html>", { headers: { "content-type": "text/html" } }))
      .mockResolvedValueOnce(new Response("ệ".repeat(100_000), { headers: { "content-type": "text/markdown" } }));
    vi.stubGlobal("fetch", fetch);
    const { api } = await loadApiModule();
    await expect(api.researchRevisionReport("rr_fixture")).resolves.toBe(markdown);
    await expect(api.researchRevisionReport("rr_fixture")).rejects.toMatchObject({ name: "ApiError", status: 200 });
    await expect(api.researchRevisionReport("rr_fixture")).rejects.toMatchObject({ name: "ApiError", status: 200 });
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch.mock.calls[0]).toEqual(["/api/research/artifacts/rr_fixture/report", expect.objectContaining({ headers: { Authorization: "Bearer report-key" } })]);
  });
  it("sends bare reverse DCF and basis inputs to their fixed read routes with bearer auth", async () => {
    vi.stubGlobal("localStorage", { getItem: () => "research-test-key", setItem: vi.fn(), removeItem: vi.fn() });
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { headers: { "content-type": "application/json" } })));
    vi.stubGlobal("fetch", fetch);
    const { api } = await loadApiModule();
    const controller = new AbortController();
    await api.researchVietnamReverseDCF({ target_price_vnd: "100", dcf: { symbol: "CASE.VN" } }, controller.signal);
    await api.researchCryptoBasis({ base: "CASE", quote: "USDT", futures: [] }, controller.signal);
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/api/research/vietnam/reverse-dcf", "/api/research/crypto/basis"]);
    for (const [, init] of fetch.mock.calls) {
      expect(init.method).toBe("POST");
      expect(init.headers).toMatchObject({ Authorization: "Bearer research-test-key" });
    }
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ target_price_vnd: "100", dcf: { symbol: "CASE.VN" } });
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ base: "CASE", quote: "USDT", futures: [] });
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("uses authenticated fixed research routes and never sends a client-certified result", async () => {
    vi.stubGlobal("localStorage", { getItem: () => "research-test-key", setItem: vi.fn(), removeItem: vi.fn() });
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { headers: { "content-type": "application/json" } })));
    vi.stubGlobal("fetch", fetch);
    const { api } = await loadApiModule();
    const input = { symbol: "CASE.VN", as_of: "2025-08-01T00:00:00Z" };
    await api.researchVietnamDCF(input);
    await api.researchVietnamComparables(input, 3);
    await api.saveResearchRevision("vietnam_dcf", input, "parent/id");
    await api.listResearchRevisions("vietnam_dcf", 10);
    await api.getResearchRevision("revision/id");
    await api.diffResearchRevisions("before/id", "after/id");
    await api.reviewResearchRevision("revision/id", "acknowledged", "Read scenario only", "Operator label");
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/research/vietnam/dcf", "/api/research/vietnam/comparables", "/api/research/artifacts",
      "/api/research/artifacts?kind=vietnam_dcf&offset=10&limit=10", "/api/research/artifacts/revision%2Fid",
      "/api/research/artifacts/after%2Fid/diff?before=before%2Fid&limit=100", "/api/research/artifacts/revision%2Fid/reviews",
    ]);
    for (const [, init] of fetch.mock.calls) expect(init.headers).toMatchObject({ Authorization: "Bearer research-test-key" });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual(input);
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ payload: input, offset: 3 });
    expect(JSON.parse(fetch.mock.calls[2][1].body)).toEqual({ kind: "vietnam_dcf", request: input, parent_revision_id: "parent/id" });
    expect(JSON.parse(fetch.mock.calls[6][1].body)).toEqual({ decision: "acknowledged", note: "Read scenario only", reviewer: "Operator label" });
  });
  it("shows bounded field validation messages without exposing raw input values", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [
      { loc: ["body", "bars", 0, "complete"], msg: "Only complete bars are accepted", input: "private-input" },
    ] }), { status: 422, headers: { "content-type": "application/json" } })));
    const { api } = await loadApiModule();
    await expect(api.forexWalkForward({} as never)).rejects.toMatchObject({ status: 422, message: "body.bars.0.complete: Only complete bars are accepted" });
  });
  it("translates the server's message-size error into a recovery instruction", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: { code: "message_too_long", max_length: 100_000, message: "Shorten input" },
    }), { status: 422, headers: { "content-type": "application/json" } })));
    const { api } = await loadApiModule();
    await expect(api.sendMessage("session", "oversized")).rejects.toMatchObject({
      status: 422, code: "message_too_long", message: expect.stringContaining("Shorten it"),
    });
  });
  beforeEach(() => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => ""),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("rejects non-JSON responses with a descriptive error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<!doctype html><html><body>SPA</body></html>", {
          status: 200,
          headers: { "content-type": "text/html" },
        }),
      ),
    );

    const { api } = await loadApiModule();

    await expect(api.getChannelStatus()).rejects.toMatchObject({
      name: "ApiError",
      status: 200,
      message: expect.stringContaining("Expected JSON from /channels/status, got text/html"),
    } satisfies Partial<ApiError>);
  });

  it("posts an authenticated connector verification request with an encoded profile id", async () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => "remote-test-key"),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", connection_state: "connected" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { api } = await loadApiModule();

    await expect(api.verifyConnector("longbridge/live sdk")).resolves.toMatchObject({ status: "ok" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/live/connectors/longbridge%2Flive%20sdk/verify?force=true",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer remote-test-key" }),
      }),
    );
  });

  it("sends the stored API key when fetching a correlation matrix", async () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => "remote-test-key"),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ labels: ["A", "B"], matrix: [[1, 0], [0, 1]] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { api } = await loadApiModule();

    await expect(api.getCorrelation("A,B", 90, "pearson")).resolves.toEqual({
      labels: ["A", "B"],
      matrix: [[1, 0], [0, 1]],
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/correlation?codes=A%2CB&days=90&method=pearson",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer remote-test-key" }),
      }),
    );
  });

  it("sends the stored API key when fetching a correlation regime timeline", async () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => "remote-test-key"),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
    const regime = {
      labels: ["A", "B"],
      dates: ["2024-01-01"],
      density: [0.5],
      smoothed: [0.5],
      fused: [0],
      episodes: [],
      params: {},
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(regime), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { api } = await loadApiModule();

    await expect(api.getCorrelationRegime("A,B", 90)).resolves.toEqual(regime);
    expect(fetchMock).toHaveBeenCalledWith(
      "/correlation/regime?codes=A%2CB&days=90",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer remote-test-key" }),
      }),
    );
  });

  it("resolves authorization errors through the active i18n key", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "server fallback" }), {
          status: 401,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    const apiModule = await loadApiModule();
    const { default: i18n } = await import("@/i18n");
    i18n.addResource(
      "en",
      "translation",
      "agent.authRequired",
      "Add an API key in Settings.",
    );
    await i18n.changeLanguage("en");

    expect(apiModule.AUTH_REQUIRED_MESSAGE).toBe("Add an API key in Settings.");
    await expect(apiModule.api.getCorrelation("A,B", 90, "pearson")).rejects.toMatchObject({
      status: 401,
      message: "Add an API key in Settings.",
    } satisfies Partial<ApiError>);
  });
});

describe("API failure recovery", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubEnv("VITE_API_TIMEOUT_MS", "1000");
    vi.stubGlobal("localStorage", { getItem: () => "", setItem: vi.fn(), removeItem: vi.fn() });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  function hangUntilAbort(signal: AbortSignal) {
    return new Promise<never>((_, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    });
  }

  it("bounds a stalled conversation-list request and clears its timer", async () => {
    vi.stubGlobal("fetch", vi.fn((_url, init) => hangUntilAbort(init.signal)));
    const { api } = await loadApiModule();
    const pending = expect(api.listSessions()).rejects.toMatchObject({
      code: "request_timeout", message: expect.stringContaining("timed out"),
    });
    await vi.advanceTimersByTimeAsync(1000);
    await pending;
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps the timeout active while reading a stalled response body", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_url, init) => ({
      ok: true,
      text: () => hangUntilAbort(init.signal),
    })));
    const { api } = await loadApiModule();
    const pending = expect(api.listSessions()).rejects.toMatchObject({ code: "request_timeout" });
    await vi.advanceTimersByTimeAsync(1000);
    await pending;
  });

  it("explains a failed server connection in the active locale", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const { api } = await loadApiModule();
    await expect(api.listSessions()).rejects.toMatchObject({
      code: "network_error", message: expect.stringContaining("Check that it is running"),
    });
  });

  it("does not replay a timed-out write and reports its uncertain outcome", async () => {
    const fetch = vi.fn((_url, init) => hangUntilAbort(init.signal));
    vi.stubGlobal("fetch", fetch);
    const { api } = await loadApiModule();
    const pending = expect(api.renameSession("session", "new title")).rejects.toMatchObject({
      code: "request_timeout", message: expect.stringContaining("check the current state"),
    });
    await vi.advanceTimersByTimeAsync(1000);
    await pending;
    expect(fetch).toHaveBeenCalledOnce();
  });
});
