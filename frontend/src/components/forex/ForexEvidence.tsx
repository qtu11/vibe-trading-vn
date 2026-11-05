import { useTranslation } from "react-i18next";
import type { ForexResearchEvidence } from "@/lib/forexApi";

/** Dated observations are separate from the executable broker quote. */
export function ForexEvidence({ evidence }: { evidence: ForexResearchEvidence }) {
  const { i18n } = useTranslation();
  const vi = i18n.language.startsWith("vi");
  const l = (en: string, vn: string) => vi ? vn : en;
  const names: Record<string, string> = {
    dxy: "DXY · Yahoo Finance", real_yield_10y: l("10Y real yield · FRED", "Lợi suất thực 10 năm · FRED"),
    broad_usd: l("Fed broad USD (separate from DXY)", "USD diện rộng của Fed (khác DXY)"),
    gold_etf: l("GLD gold holdings · SPDR", "Lượng vàng GLD · SPDR"),
    gold_futures_volume: l("GC futures volume · CME", "Khối lượng hợp đồng GC · CME"),
  };
  const status = (value: string) => value === "ok" ? l("Available", "Đã lấy")
    : value === "stale" ? l("Stale", "Dữ liệu cũ")
    : value === "partial" ? l("Partial", "Chưa đủ") : l("Unavailable", "Chưa lấy được");
  return <details className="rounded-lg border p-3 text-xs">
    <summary className="cursor-pointer font-medium">{l("Analysis data & sources", "Dữ liệu và nguồn phân tích")}</summary>
    <div className="mt-3 space-y-3">
      <p>{evidence.medium_term_price_context_ready
        ? l("Higher timeframe price history is available. It does not guarantee a forecast.", "Đã có lịch sử giá khung lớn. Dữ liệu này không bảo đảm dự báo đúng.")
        : l("Higher timeframe history is incomplete or stale; new AI entries are blocked.", "Lịch sử khung lớn chưa đủ hoặc đã cũ; AI bị chặn mở lệnh mới.")}</p>
      <div className="overflow-x-auto"><table className="w-full text-left">
        <caption className="mb-1 text-left font-medium">{l("Completed broker candles", "Nến broker đã đóng")}</caption>
        <thead><tr><th className="p-1">{l("Frame", "Khung")}</th><th className="p-1">{l("Bars", "Số nến")}</th><th className="p-1">{l("First / last (UTC)", "Đầu / cuối (UTC)")}</th><th className="p-1">{l("Status", "Trạng thái")}</th></tr></thead>
        <tbody>{Object.entries(evidence.timeframes).map(([frame, row]) => <tr key={frame} className="border-t">
          <td className="p-1 font-mono">{({ "5m": "M5", "1h": "H1", "4h": "H4", "1d": "D1" } as Record<string, string>)[frame] || frame}</td>
          <td className="p-1">{row.candle_count ?? "—"}</td>
          <td className="p-1">{row.first_bar?.slice(0, 16).replace("T", " ") ?? "—"}<br />{row.last_bar?.slice(0, 16).replace("T", " ") ?? "—"}</td>
          <td className="p-1">{status(row.status)}</td>
        </tr>)}</tbody>
      </table></div>
      {Object.values(evidence.timeframes).some(row => row.indicators) && <div className="overflow-x-auto"><table className="w-full text-left">
        <caption className="mb-1 text-left font-medium">{l("Calculated indicators · full fetched window", "Chỉ báo tính toán · toàn bộ cửa sổ đã lấy")}</caption>
        <thead><tr><th className="p-1">{l("Frame", "Khung")}</th>{["EMA20", "SMA50", "SMA200", "RSI14", "ATR14"].map(k => <th key={k} className="p-1">{k}</th>)}</tr></thead>
        <tbody>{Object.entries(evidence.timeframes).map(([frame, row]) => <tr key={frame} className="border-t">
          <td className="p-1 font-mono">{({ "5m": "M5", "1h": "H1", "4h": "H4", "1d": "D1" } as Record<string, string>)[frame] || frame}</td>
          {["ema_20", "sma_50", "sma_200", "rsi_14", "atr_14"].map(k => <td key={k} className="p-1 font-mono">{row.indicators?.[k] ?? "—"}</td>)}
        </tr>)}</tbody>
      </table></div>}
      <ul className="space-y-2">{Object.entries(evidence.macro).map(([name, row]) => {
        const value = row.latest?.value ?? row.latest?.tonnes;
        const unit = row.unit === "percent" ? "%" : row.unit === "tonnes_of_gold" ? l("tonnes", "tấn")
          : row.unit === "contracts" ? l("contracts", "hợp đồng") : l("index points", "điểm chỉ số");
        return <li key={name}>
          {row.source_url ? <a href={row.source_url} target="_blank" rel="noreferrer" className="underline">{names[name] || name}</a> : names[name] || name}
          {" · "}{status(row.status)}{row.as_of && ` · ${row.as_of}`}
          {value != null && ` · ${value.toLocaleString(vi ? "vi-VN" : "en-US")} ${unit}`}
        </li>;
      })}</ul>
      <p className="text-muted-foreground">{l("Daily macro releases have their own observation dates. MT5 volume is tick count. GC futures and GLD shares are separate markets; GLD net-creation estimates cover one fund.", "Nguồn vĩ mô cập nhật theo ngày quan sát riêng. Volume MT5 là số tick. Hợp đồng GC và chứng chỉ GLD thuộc thị trường riêng; ước lượng phát hành ròng GLD chỉ bao phủ một quỹ.")}</p>
    </div>
  </details>;
}
