import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ForexLiveChart } from "./ForexLiveChart";
import { ForexTradeCards } from "@/components/chat/ForexTradeCards";
import { parseForexTradePlan, type ForexTradePlan } from "@/lib/forexTradePlan";
import { forexRequest, type ForexConnection } from "@/lib/forexApi";
import type { ForexFrame } from "@/lib/forexChart";
import { button, field, panel } from "./ForexConnectionForm";

export function ForexMarket({ connection, initialSymbol = "", initialFrame = "5m" }: { connection: ForexConnection; initialSymbol?: string; initialFrame?: ForexFrame }) {
  const { i18n } = useTranslation();
  const vi = i18n.language.startsWith("vi");
  const l = (en: string, vn: string) => vi ? vn : en;
  const [symbol, setSymbol] = useState(initialSymbol || connection.symbols[0] || "XAUUSDm");
  const [draft, setDraft] = useState(symbol);
  const [frame, setFrame] = useState<ForexFrame>(initialFrame);
  const [plan, setPlan] = useState<ForexTradePlan>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  useEffect(() => {
    generation.current += 1; setPlan(undefined); setError(""); setBusy(false);
    return () => { generation.current += 1; };
  }, [connection.id, symbol, frame]);
  const analyze = async () => {
      const requestGeneration = generation.current;
      setBusy(true); setError("");
      try {
        const result = await forexRequest<unknown>("/api/forex/research-plan", { connection_id: connection.id, symbol,
          forecast_timeframe: frame, entry_mode: "auto", include_macro: true }, "POST", 270000);
        const parsed = parseForexTradePlan(result);
        if (!parsed || parsed.symbol !== symbol || parsed.connection_id !== connection.id) throw new Error(l("Invalid analysis response", "Phản hồi phân tích không hợp lệ"));
        if (generation.current === requestGeneration) setPlan(parsed);
      } catch (e) { if (generation.current === requestGeneration) setError(e instanceof Error ? e.message : String(e)); }
      finally { if (generation.current === requestGeneration) setBusy(false); }
  };
  if (connection.connector !== "mt5") return <section className={panel}><h2 className="font-semibold">{l("Live candlesticks", "Biểu đồ nến trực tiếp")}</h2><p className="text-sm">{l("Choose an MT5 connection for the native candle chart.", "Chọn kết nối MT5 để mở biểu đồ nến native.")}</p></section>;
  return <section className={panel}>
    <h2 className="font-semibold">{l("Live candles & AI pattern analysis", "Nến trực tiếp & AI phân tích mô hình")}</h2>
    <form className="flex flex-wrap items-end gap-2" onSubmit={e => { e.preventDefault(); const s = draft.trim(); if (s) setSymbol(s); }}>
      <label className="text-xs">{l("Exact native symbol", "Mã chính xác tại broker")}<input className={`${field} mt-1`} value={draft} maxLength={64} onChange={e => setDraft(e.target.value)} /></label>
      <button className={button} type="submit">{l("Load candles", "Xem nến")}</button>
      <button className={`${button} bg-primary text-primary-foreground`} type="button" disabled={busy} onClick={() => void analyze()}>{busy ? l("AI analyzing closed candles…", "AI đang phân tích nến đã đóng…") : l("AI: patterns & trend outlook", "AI: mô hình nến & dự báo xu hướng")}</button>
    </form>
    <p className="text-xs text-muted-foreground">{l("The chart keeps updating. AI analyzes a dated snapshot of closed candles on M5/H1/H4/D1, not every tick, and never sends orders here.", "Chart tiếp tục cập nhật. AI phân tích snapshot nến đã đóng trên M5/H1/H4/D1, không suy luận ở mọi tick và không gửi lệnh tại đây.")}</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <ForexLiveChart connectionId={connection.id} symbol={symbol} frame={frame} onFrameChange={setFrame} />
    {plan && <ForexTradeCards plan={plan} />}
  </section>;
}
