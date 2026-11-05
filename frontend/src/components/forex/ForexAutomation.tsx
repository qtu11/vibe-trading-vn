import { useState } from "react";
import { useTranslation } from "react-i18next";
import { forexPath, forexRequest, type ForexConnection, type ForexProposal, type ForexRunner } from "@/lib/forexApi";
import { button, field, panel } from "./ForexConnectionForm";

export function ForexAutomation({ connection, status, reload, onError }: {
  connection: ForexConnection; status: ForexRunner; reload: () => Promise<void>; onError: (message: string) => void;
}) {
  const { i18n } = useTranslation();
  const l = (en: string, vi: string) => i18n.language.startsWith("vi") ? vi : en;
  const [symbol, setSymbol] = useState(connection.symbols[0] || "");
  const [quantity, setQuantity] = useState(connection.limits.max_quantity);
  const [timeframe, setTimeframe] = useState("15m");
  const [fast, setFast] = useState(10); const [slow, setSlow] = useState(30);
  const [distance, setDistance] = useState(200); const [reward, setReward] = useState("2");
  const [busy, setBusy] = useState(false); const [agreed, setAgreed] = useState(false);
  const [proposal, setProposal] = useState<ForexProposal | null>(null);
  const [mandate, setMandate] = useState<string | null>(null);
  const action = async (fn: () => Promise<void>) => {
    setBusy(true); onError("");
    try { await fn(); await reload(); } catch (e) { onError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return <section className={panel}>
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">{l("Automatic strategy", "Chiến lược tự động")}</h2><span className="rounded-full border px-3 py-1 font-mono text-xs">{status.status}</span></div>
    <p className="text-xs text-muted-foreground">{l("SMA crossover on completed candles. Enters only when the account is flat; broker SL/TP handle exits. A restart requires an explicit start. No LLM is required.", "SMA giao cắt trên nến đã đóng. Chỉ mở lệnh khi tài khoản không có vị thế/lệnh chờ; SL/TP ở broker quản lý thoát lệnh. Sau khởi động lại cần bấm chạy. Không cần LLM.")}</p>
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <label className="space-y-1 text-xs">Symbol<select className={field} disabled={status.running} value={symbol} onChange={e => setSymbol(e.target.value)}><option value="">—</option>{connection.symbols.map(s => <option key={s}>{s}</option>)}</select></label>
      <label className="space-y-1 text-xs">{l("Quantity", "Khối lượng")}<input disabled={status.running} className={field} value={quantity} onChange={e => setQuantity(e.target.value)} /></label>
      <label className="space-y-1 text-xs">{l("Timeframe", "Khung nến")}<select disabled={status.running} className={field} value={timeframe} onChange={e => setTimeframe(e.target.value)}>{["5m", "15m", "1h", "4h"].map(t => <option key={t}>{t}</option>)}</select></label>
      <label className="space-y-1 text-xs">SMA fast<input disabled={status.running} className={field} type="number" min={2} max={100} value={fast} onChange={e => setFast(Number(e.target.value))} /></label>
      <label className="space-y-1 text-xs">SMA slow<input disabled={status.running} className={field} type="number" min={3} max={200} value={slow} onChange={e => setSlow(Number(e.target.value))} /></label>
      <label className="space-y-1 text-xs">{l("Stop distance (points)", "Khoảng stop (point)")}<input disabled={status.running} className={field} type="number" min={1} value={distance} onChange={e => setDistance(Number(e.target.value))} /></label>
      <label className="space-y-1 text-xs">{l("Take-profit / stop distance", "Khoảng take-profit / stop")}<input disabled={status.running} className={field} type="number" min="0.1" step="any" value={reward} onChange={e => setReward(e.target.value)} /></label>
    </div>
    {connection.environment === "live" && <div className="space-y-3 rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">{l("Live execution needs separate consent bound to this account. Limits are checked for every order.", "Live cần consent riêng gắn đúng tài khoản này. Giới hạn được kiểm tra lại ở từng lệnh.")}</p>
      <button className={button} disabled={busy || status.running} onClick={() => void action(async () => setProposal(await forexRequest<ForexProposal>(`${forexPath(connection.id)}/mandate-proposal`, {})))}>{l("Prepare live mandate", "Chuẩn bị mandate live")}</button>
      {proposal && <>
        <label className="flex gap-2 text-xs"><input type="checkbox" checked={agreed} onChange={e => setAgreed(e.target.checked)} /><span>{l("I authorize one day of bounded live trading on account", "Tôi cấp quyền giao dịch live có giới hạn trong một ngày cho tài khoản")} <strong>{connection.account_ref}</strong>.</span></label>
        <div className="flex flex-wrap gap-2">{proposal.profiles.map(p => <button className={button} key={p.ordinal} disabled={!agreed || busy} onClick={() => void action(async () => {
          const response = await forexRequest<{ expires_at: string }>("/mandate/commit", { broker: connection.mandate_key,
            account_ref: connection.account_ref, proposal_id: proposal.proposal_id, selected_ordinal: p.ordinal,
            consent_ack: true, lifetime_days: 1 }); setMandate(response.expires_at); setProposal(null); setAgreed(false);
        })}><span className="block">#{p.ordinal}: ${p.max_order_usd} / {p.daily_trade_cap} {l("per day", "mỗi ngày")}</span><span className="mt-1 block text-xs text-muted-foreground">{l("Gross cap", "Trần exposure")}: ${p.max_total_exposure_usd} · {l("Leverage", "Đòn bẩy")}: {p.leverage} · {p.instruments.join(", ")}</span></button>)}</div>
      </>}
      {mandate && <p className="text-xs">{l("Mandate expires", "Mandate hết hạn")}: {mandate}</p>}
    </div>}
    <div className="flex flex-wrap gap-2">
      <button className={`${button} bg-primary text-primary-foreground`} disabled={busy || status.running || !connection.execution_enabled || connection.halted || !symbol || fast >= slow} onClick={() => void action(async () => {
        await forexRequest(`${forexPath(connection.id)}/runner/start`, { symbol, quantity, timeframe, fast, slow,
          stop_distance_points: distance, reward_ratio: reward, interval_seconds: 60 });
      })}>{l("Start strategy", "Chạy chiến lược")}</button>
      <button className={button} disabled={busy || !status.running} onClick={() => void action(async () => { await forexRequest(`${forexPath(connection.id)}/runner/stop`, {}); })}>{l("Stop strategy", "Dừng chiến lược")}</button>
    </div>
    {status.error && <p className="text-sm text-destructive">{status.error}</p>}
    {status.checked_at && <p className="text-xs text-muted-foreground">{l("Last check", "Lần kiểm tra cuối")}: {status.checked_at}</p>}
  </section>;
}
