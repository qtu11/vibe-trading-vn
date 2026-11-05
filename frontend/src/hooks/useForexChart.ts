import { useEffect, useRef, useState } from "react";
import { fetchForexChart, type ForexChartSnapshot, type ForexFrame } from "@/lib/forexChart";

/** Poll terminal bars (including zero bar) without overlap or stale-account races. */
export function useForexChart(connection: string, symbol: string, frame: ForexFrame, paused: boolean) {
  const [snapshot, setSnapshot] = useState<ForexChartSnapshot | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const binding = useRef<string | null>(null);
  useEffect(() => { setSnapshot(null); setError(""); binding.current = null; }, [connection, symbol, frame]);
  useEffect(() => {
    if (!connection || !symbol || paused) { setLoading(false); return; }
    let active = true, inFlight = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    const poll = async () => {
      if (!active || inFlight) return;
      if (document.visibilityState === "hidden") { timer = setTimeout(poll, 3000); return; }
      inFlight = true; setLoading(true);
      controller = new AbortController();
      const timeout = setTimeout(() => controller?.abort(), 20000);
      try {
        const result = await fetchForexChart(connection, symbol, frame, controller.signal);
        if (active) {
          if (binding.current && result.binding_hash !== binding.current) throw new Error("Connection changed; reselect the account before continuing");
          binding.current = result.binding_hash;
          setSnapshot(result); setError("");
        }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.name === "AbortError" ? "MT5 chart request timed out" : e.message : String(e));
      } finally {
        clearTimeout(timeout); inFlight = false;
        if (active) { setLoading(false); timer = setTimeout(poll, 3000); }
      }
    };
    const visible = () => { if (document.visibilityState === "visible" && !inFlight) { clearTimeout(timer); void poll(); } };
    document.addEventListener("visibilitychange", visible);
    void poll();
    return () => { active = false; clearTimeout(timer); controller?.abort(); document.removeEventListener("visibilitychange", visible); };
  }, [connection, symbol, frame, paused]);
  return { snapshot, error, loading };
}
