/**
 * Frontend Hook: useRealtimeCandleBuffer
 * Dual-tier event buffering: Gom 30-60 ticks/s thanh 1 dot cap nhat ECharts tren moi frame rAF (16.6ms).
 * Ho tro toi uu hoa do tre va hieu nang render cho bieu do nến thoi gian thuc XAU/USD va Co phieu.
 */
import { useEffect, useRef } from "react";

export interface RealtimeTick {
  symbol: string;
  bid: number;
  ask: number;
  time_msc: number;
  volume: number;
}

export type CandleBarTuple = [string, number, number, number, number, number]; // [time, open, close, high, low, volume]

export function useRealtimeCandleBuffer(
  onFrameUpdate: (latestTick: RealtimeTick, updatedFormingBar: CandleBarTuple) => void
) {
  const tickBufferRef = useRef<RealtimeTick[]>([]);
  const frameIdRef = useRef<number>(0);
  const formingBarRef = useRef<CandleBarTuple | null>(null);

  const pushTick = (tick: RealtimeTick) => {
    tickBufferRef.current.push(tick);
    if (!frameIdRef.current) {
      frameIdRef.current = requestAnimationFrame(processBuffer);
    }
  };

  const processBuffer = () => {
    frameIdRef.current = 0;
    const ticks = tickBufferRef.current;
    if (ticks.length === 0) return;

    // Lay tick moi nhat trong frame
    const latest = ticks[ticks.length - 1];
    const midPrice = (latest.bid + latest.ask) / 2.0;

    // Cap nhat nen dang hinh thanh (forming bar)
    if (formingBarRef.current) {
      const bar = formingBarRef.current;
      bar[2] = midPrice;                     // Close
      bar[3] = Math.max(bar[3], midPrice);   // High
      bar[4] = Math.min(bar[4], midPrice);   // Low
      bar[5] += ticks.length;                // Tick count volume
      onFrameUpdate(latest, bar);
    }

    tickBufferRef.current = [];
  };

  useEffect(() => {
    return () => {
      if (frameIdRef.current) {
        cancelAnimationFrame(frameIdRef.current);
      }
    };
  }, []);

  return { pushTick, formingBarRef };
}
