import { act, renderHook } from "@testing-library/react";
import { useForexChart } from "../useForexChart";
import type { ForexChartSnapshot } from "@/lib/forexChart";

const mock = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/forexChart", () => ({ fetchForexChart: mock.fetch }));
const snapshot = (id = "fixture") => ({ binding_hash: "a".repeat(64), connection_id: id, symbol: "XAUUSDm", bars: [], quote: {} }) as unknown as ForexChartSnapshot;
beforeEach(() => { vi.useFakeTimers(); mock.fetch.mockReset(); });
afterEach(() => vi.useRealTimers());

it("does not overlap native reads and stops polling on unmount", async () => {
  let resolve!: (v: ForexChartSnapshot) => void;
  mock.fetch.mockReturnValueOnce(new Promise<ForexChartSnapshot>(r => { resolve = r; })).mockResolvedValue(snapshot());
  const { result, unmount } = renderHook(() => useForexChart("fixture", "XAUUSDm", "5m", false));
  await act(async () => { vi.advanceTimersByTime(9000); });
  expect(mock.fetch).toHaveBeenCalledTimes(1);
  await act(async () => resolve(snapshot()));
  expect(result.current.snapshot?.connection_id).toBe("fixture");
  await act(async () => { vi.advanceTimersByTime(3000); });
  expect(mock.fetch).toHaveBeenCalledTimes(2);
  unmount();
  await act(async () => { vi.advanceTimersByTime(9000); });
  expect(mock.fetch).toHaveBeenCalledTimes(2);
});

it("discards a late response from a previously selected account", async () => {
  let resolve!: (v: ForexChartSnapshot) => void;
  mock.fetch.mockReturnValueOnce(new Promise<ForexChartSnapshot>(r => { resolve = r; })).mockResolvedValue(snapshot("second"));
  const { result, rerender } = renderHook(({ id }) => useForexChart(id, "XAUUSDm", "5m", false), { initialProps: { id: "first" } });
  await act(async () => rerender({ id: "second" }));
  await act(async () => resolve(snapshot("first")));
  expect(result.current.snapshot?.connection_id).toBe("second");
});

it("retains last data on failure with an explicit error, and does not poll while paused", async () => {
  mock.fetch.mockResolvedValueOnce(snapshot()).mockRejectedValue(new Error("MT5 disconnected"));
  const { result, rerender } = renderHook(({ paused }) => useForexChart("fixture", "XAUUSDm", "5m", paused), { initialProps: { paused: false } });
  await act(async () => {});
  await act(async () => { vi.advanceTimersByTime(3000); });
  expect(result.current.error).toContain("MT5 disconnected");
  expect(result.current.snapshot?.connection_id).toBe("fixture");
  rerender({ paused: true });
  const count = mock.fetch.mock.calls.length;
  await act(async () => { vi.advanceTimersByTime(10000); });
  expect(mock.fetch).toHaveBeenCalledTimes(count);
});
