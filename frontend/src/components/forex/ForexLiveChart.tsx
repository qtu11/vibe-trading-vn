import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Pause, Play } from "lucide-react";
import { useForexChart } from "@/hooks/useForexChart";
import { forexFrameLabel, patternLabel, type ForexFrame } from "@/lib/forexChart";
import { ForexCandlePlot } from "./ForexCandlePlot";

export function ForexLiveChart({ connectionId, symbol, frame, onFrameChange }: {
  connectionId: string; symbol: string; frame: ForexFrame; onFrameChange: (f: ForexFrame) => void;
}) {
  const { i18n } = useTranslation();
  const vi = i18n.language.startsWith("vi");
  const l = (en: string, vn: string) => vi ? vn : en;
  const [paused, setPaused] = useState(false);
  const [now, setNow] = useState(Date.now);
  const { snapshot: data, error, loading } = useForexChart(connectionId, symbol, frame, paused);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const quoteAge = data ? (now - Date.parse(data.quote.timestamp)) / 1000 : Infinity;
  const fresh = !!data && data.quote.is_fresh && quoteAge >= -2 && quoteAge <= data.quote.max_age_seconds && !error;
  const last = data?.bars[data.bars.length - 1];
  const structure = data?.price_action.structure;
  return <section aria-label={l("Live MT5 candlesticks", "Nến MT5 cập nhật liên tục")} className="space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h3 className="font-semibold">{symbol} · {forexFrameLabel(frame)}</h3>
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs">{l("Timeframe", "Khung nến")} <select className="rounded border bg-background px-2 py-1.5" value={frame} onChange={e => onFrameChange(e.target.value as ForexFrame)}>
          {(["5m", "1h", "4h", "1d"] as const).map(f => <option key={f} value={f}>{forexFrameLabel(f)}</option>)}
        </select></label>
        <button className="inline-flex items-center gap-1 rounded border px-2 py-1.5 text-xs" onClick={() => setPaused(p => !p)}>
          {paused ? <Play size={13} /> : <Pause size={13} />}{paused ? l("Resume updates", "Tiếp tục cập nhật") : l("Pause updates", "Tạm dừng cập nhật")}
        </button>
      </div>
    </div>
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs">
      <span className={paused || !fresh ? "text-amber-700 dark:text-amber-400" : "text-emerald-700 dark:text-emerald-400"}>
        {paused ? l("PAUSED", "ĐÃ TẠM DỪNG") : !data ? l("CONNECTING", "ĐANG KẾT NỐI") : fresh ? l("UPDATING · ~3s polling", "ĐANG CẬP NHẬT · lấy dữ liệu ~3 giây/lần") : l("STALE / DISCONNECTED", "BÁO GIÁ CŨ / MẤT KẾT NỐI")}
      </span>
      {data && <span className="font-mono">Bid {data.quote.bid} / Ask {data.quote.ask}</span>}
    </div>
    {error && <p role="alert" className="rounded border border-destructive/40 p-2 text-xs text-destructive">{error} {data && l("Last received data remains visible.", "Đang giữ dữ liệu nhận được lần cuối.")}</p>}
    {data ? <>
      <p className="text-xs text-muted-foreground">MT5 · {data.broker_server} · {data.environment.toUpperCase()} · {l("Broker tick", "Tick broker")}: {data.quote.timestamp.replace("T", " ")} {loading && ` · ${l("refreshing", "đang làm mới")}`}</p>
      <ForexCandlePlot snapshot={data} />
      <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs" aria-label={l("Latest candle OHLC", "OHLC nến mới nhất")}>
        <span>{last?.time.slice(0, 16).replace("T", " ")} UTC</span><span>O {last?.open}</span><span>H {last?.high}</span><span>L {last?.low}</span><span>C {last?.close}</span>
        <strong>{last?.complete ? l("CLOSED", "ĐÃ ĐÓNG") : l("FORMING", "CHƯA ĐÓNG")}</strong>
      </div>
      <p className="text-xs text-muted-foreground">{l("The lighter final candle is the terminal's current bar and may change. EMA20 includes that bar. Pattern analysis uses closed candles only. Volume below is tick count, not global traded volume. No synthetic bars fill market gaps.", "Nến cuối mờ hơn là nến đang hình thành tại terminal, có thể thay đổi. EMA20 có tính nến này. Phân tích mô hình chỉ dùng nến đã đóng. Cột dưới là số tick, không phải khối lượng giao dịch toàn thị trường. Không tạo nến giả để lấp khoảng nghỉ.")}</p>
      <div className="rounded-lg border p-3 text-xs">
        <p className="font-medium">{l("Closed-candle evidence", "Bằng chứng từ nến đã đóng")} · {data.price_action.closed_count} {l("bars", "nến")}</p>
        <p className="mt-1">{l("Confirmed swing structure", "Cấu trúc swing đã xác nhận")}: {structure === "higher_highs_higher_lows" ? "HH / HL ↑" : structure === "lower_highs_lower_lows" ? "LH / LL ↓" : structure === "mixed_or_range" ? l("Mixed / range", "Xen kẽ / đi ngang") : l("Insufficient confirmed pivots", "Chưa đủ pivot được xác nhận")}</p>
        <p className="mt-1">{l("20-bar support / resistance", "Hỗ trợ / kháng cự của 20 nến trước")}: {data.price_action.support_20 ?? "—"} / {data.price_action.resistance_20 ?? "—"}</p>
        <ul className="mt-2 flex flex-wrap gap-2">{data.price_action.patterns.slice(-4).map(p => <li key={`${p.name}:${p.time}`} className="rounded border px-2 py-1">{patternLabel(p.name)} · {p.time.slice(5, 16).replace("T", " ")} UTC</li>)}</ul>
        {!data.price_action.patterns.length && <p className="mt-1 text-muted-foreground">{l("No shape matched the configured rules in the last closed candles.", "Chưa có dạng nến khớp bộ quy tắc trong các nến đóng gần nhất.")}</p>}
        <p className="mt-2 text-muted-foreground">{l("Shape detections are candidates; they do not guarantee a reversal or future trend.", "Dạng nến là ứng viên theo quy tắc, chưa xác nhận đảo chiều hoặc bảo đảm xu hướng tương lai.")}</p>
      </div>
      <details className="rounded border p-2 text-xs"><summary className="cursor-pointer">{l("Accessible OHLC table · latest candles", "Bảng OHLC · các nến cuối")}</summary>
        <div className="mt-2 overflow-x-auto"><table className="w-full text-left"><thead><tr>{["UTC", "Open", "High", "Low", "Close", "Ticks", l("State", "Trạng thái")].map(h => <th className="p-1" key={h}>{h}</th>)}</tr></thead>
          <tbody>{data.bars.slice(-8).map(b => <tr key={b.time} className="border-t"><td className="p-1 whitespace-nowrap">{b.time.slice(0, 19).replace("T", " ")}</td>{[b.open, b.high, b.low, b.close, b.volume].map((v, i) => <td key={i} className="p-1 font-mono">{v}</td>)}<td className="p-1 whitespace-nowrap">{b.complete ? l("Closed", "Đã đóng") : l("Forming", "Chưa đóng")}</td></tr>)}</tbody>
        </table></div>
      </details>
    </> : <div className="flex h-96 items-center justify-center rounded-lg border bg-muted/20 text-sm text-muted-foreground" role="status">{error ? l("Choose a working MT5 connection to load candles.", "Chọn kết nối MT5 đang hoạt động để lấy nến.") : l("Reading actual candles from the saved MT5 session…", "Đang đọc nến thật từ phiên MT5 đã lưu…")}</div>}
  </section>;
}
