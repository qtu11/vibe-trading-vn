import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { BrainCircuit } from "lucide-react";
import { forexPath, forexRequest, type ForexAccount, type ForexAnalysis, type ForexConnection, type ForexIntent, type ForexOrder, type ForexRunner } from "@/lib/forexApi";
import { button, field, panel } from "./ForexConnectionForm";
import { ForexEvidence } from "./ForexEvidence";

export function ForexAI({ connection, runner, reload, onError }: {
  connection: ForexConnection; runner: ForexRunner; reload: () => Promise<void>; onError: (message: string) => void;
}) {
  const { i18n } = useTranslation();
  const l = (en: string, vi: string) => i18n.language.startsWith("vi") ? vi : en;
  const [symbol, setSymbol] = useState(connection.symbols[0] || "");
  const [timeframe, setTimeframe] = useState("5m");
  const [quantity, setQuantity] = useState(connection.limits.max_quantity);
  const [confidence, setConfidence] = useState(0.75);
  const [analysis, setAnalysis] = useState<ForexAnalysis | null>(null);
  const [account, setAccount] = useState<ForexAccount | null>(null);
  const [readError, setReadError] = useState("");
  const [busy, setBusy] = useState(false);
  const path = forexPath(connection.id);
  const refresh = useCallback(async () => {
    const [state, current] = await Promise.all([
      forexRequest<{ analysis: ForexAnalysis | null }>(`${path}/ai`),
      forexRequest<{ data: ForexAccount }>(`${path}/account`),
    ]);
    return { state, current };
  }, [path]);
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const { state, current } = await refresh();
        if (active) { setAnalysis(state.analysis); setAccount(current.data); setReadError(""); }
      } catch (e) { if (active) { setAccount(null); setReadError(e instanceof Error ? e.message : String(e)); } }
    };
    void poll(); const interval = window.setInterval(() => void poll(), 15000);
    return () => { active = false; window.clearInterval(interval); };
  }, [refresh]);
  const action = async (fn: () => Promise<void>) => {
    setBusy(true); onError("");
    try { await fn(); } catch (e) { onError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); try { await reload(); } catch (e) { onError(e instanceof Error ? e.message : String(e)); } }
  };
  const strategy = { symbol, quantity, timeframe, lookback: 60, interval_seconds: 60, minimum_confidence: confidence };
  const demo = connection.connector === "mt5" && connection.environment === "demo";
  return <section className={panel}>
    <div><h2 className="flex items-center gap-2 font-semibold"><BrainCircuit className="h-5 w-5 text-primary" />{l("AI analysis & automatic demo trading", "AI phân tích & tự giao dịch Demo")}</h2>
      <p className="mt-1 text-xs text-muted-foreground">{l("The AI configured in Settings analyzes completed broker candles and chooses BUY, SELL, HOLD or CLOSE. Every order passes application limits. Only positions opened by this connection can be closed.", "AI trong Cài đặt phân tích nến đã đóng từ broker rồi chọn BUY, SELL, HOLD hoặc CLOSE. Mỗi lệnh phải qua giới hạn của ứng dụng. Chỉ đóng vị thế do kết nối này mở.")}</p></div>
    {connection.connector === "mt5" && <p className="text-xs text-muted-foreground">{l("MT5 analysis also reads M5/H1/H4/D1 trend context and dated macro sources. The selected timeframe controls entry timing.", "Phân tích MT5 đọc thêm bối cảnh M5/H1/H4/D1 và nguồn vĩ mô có ngày quan sát. Khung được chọn dùng để xác định thời điểm vào lệnh.")}</p>}
    {readError && <p role="status" className="text-sm text-amber-700">{readError}</p>}
    {account && <div className="rounded-lg border bg-muted/30 p-3 text-sm space-y-2">
      <p className="font-medium">{account.account_ref} · {connection.server} · {account.environment.toUpperCase()} · {account.equity} {account.currency}</p>
      <p>{account.trade_allowed ? l("Terminal execution permission is enabled.", "Terminal đã cho phép thực thi.") : l("Connected for data; MT5 execution permission is disabled.", "Đã kết nối dữ liệu; MT5 đang chặn thực thi.")}</p>
      {account.terminal_trade_allowed === false && <p className="text-amber-700">{l("Enable the Algo Trading button in MT5 (Ctrl+E).", "Bật nút Algo Trading trong MT5 (Ctrl+E).")}</p>}
      {account.external_api_disabled && <p className="text-amber-700">{l("MT5 → Tools → Options → Expert Advisors: uncheck Disable automatic trading through the external Python API.", "MT5 → Công cụ → Tùy chọn (Ctrl+O) → Expert Advisors: bỏ chọn Disable automatic trading through the external Python API.")}</p>}
    </div>}
    <div className="grid grid-cols-2 gap-3">
      <label className="text-xs space-y-1">{l("AI symbol", "Symbol AI")}<select className={field} value={symbol} disabled={runner.running} onChange={e => setSymbol(e.target.value)}>{!symbol && <option value="">{l("Save an allowed symbol first", "Lưu symbol được phép trước")}</option>}{connection.symbols.map(s => <option key={s}>{s}</option>)}</select></label>
      <label className="text-xs space-y-1">{l("AI entry timeframe", "Khung vào lệnh AI")}<select className={field} value={timeframe} disabled={runner.running} onChange={e => setTimeframe(e.target.value)}>{["5m", "15m", "1h", "4h"].map(t => <option key={t}>{t}</option>)}</select></label>
      <label className="text-xs space-y-1">{l("AI quantity (lots)", "Khối lượng AI (lot)")}<input className={field} value={quantity} disabled={runner.running} onChange={e => setQuantity(e.target.value)} inputMode="decimal" /></label>
      <label className="text-xs space-y-1">{l("Minimum AI confidence", "Độ tin cậy AI tối thiểu")}<input className={field} type="number" min={0.5} max={1} step={0.05} value={confidence} disabled={runner.running} onChange={e => setConfidence(Number(e.target.value))} /></label>
    </div>
    <div className="flex flex-wrap gap-2">
      <button className={button} disabled={busy || !symbol || runner.running} onClick={() => void action(async () => setAnalysis(await forexRequest<ForexAnalysis>(`${path}/ai/analyze`, strategy)))}>{busy ? l("Processing…", "Đang xử lý…") : l("Analyze with AI", "Phân tích bằng AI")}</button>
      <button className={`${button} bg-primary text-primary-foreground`} disabled={busy || runner.running || !demo || !symbol || !connection.execution_enabled || !account?.trade_allowed || connection.halted} onClick={() => void action(async () => { await forexRequest(`${path}/ai/start`, strategy); })}>{l("Start automatic AI demo", "Chạy AI tự động Demo")}</button>
      <button className={button} disabled={busy || !runner.running} onClick={() => void action(async () => { await forexRequest(`${path}/runner/stop`, {}); })}>{l("Stop AI / strategy", "Dừng AI / chiến lược")}</button>
    </div>
    {!connection.execution_enabled && <p className="text-xs text-muted-foreground">{l("Enable protected execution in connection settings to start the demo runner.", "Bật thực thi có kiểm soát trong cấu hình kết nối để chạy AI Demo.")}</p>}
    <p role="status" className="text-xs">{runner.mode === "ai" ? "AI" : "Runner"}: {runner.running ? l("Running", "Đang chạy") : l("Stopped", "Đã dừng")} · {runner.status}{runner.error && ` · ${runner.error}`}</p>
    {analysis && <div className="rounded-lg border p-3 space-y-2 text-sm" aria-live="polite">
      {analysis.decision ? <>
        <div className="flex justify-between gap-2 font-semibold"><span>{analysis.decision.action.toUpperCase()}</span><span>{Math.round(analysis.decision.confidence * 100)}%</span></div>
        <p className="whitespace-pre-wrap">{analysis.decision.rationale}</p>
        {analysis.decision.confidence < confidence && <p className="text-amber-700">{l("Below the confidence threshold; this decision will not open or close a position.", "Chưa đạt ngưỡng tin cậy; quyết định này không được dùng để mở hoặc đóng vị thế.")}</p>}
        {analysis.expires_at && new Date(analysis.expires_at).getTime() < Date.now() && <p className="text-muted-foreground">{l("This analysis has expired. A new completed candle is required for another decision.", "Phân tích này đã hết hạn. Chờ nến mới đóng để tạo quyết định tiếp theo.")}</p>}
        {analysis.decision.stop_loss && <p className="font-mono text-xs">SL {analysis.decision.stop_loss} · TP {analysis.decision.take_profit}</p>}
        <p className="break-all text-xs text-muted-foreground">{analysis.model?.provider} · {analysis.model?.model} · {analysis.last_bar} · {analysis.execution_status}</p>
      </> : <p>{analysis.error || analysis.status}</p>}
    </div>}
    {analysis?.evidence && <ForexEvidence evidence={analysis.evidence} />}
    {!!account?.positions.length && <div className="space-y-2"><h3 className="text-sm font-medium">{l("Open positions", "Vị thế đang mở")}</h3>{account.positions.map(p => <div key={p.ticket} className="flex flex-wrap items-center justify-between gap-2 rounded border p-2 text-xs"><span>#{p.ticket} · {p.symbol} · {p.type === 0 ? "BUY" : "SELL"} · {p.volume} lot · P/L {p.profit}</span>{demo && p.managed ? <button className={button} disabled={busy || !connection.execution_enabled || !account.trade_allowed || connection.halted || runner.running} onClick={() => void action(async () => {
      const order: ForexOrder = { action: "close", position_ticket: String(p.ticket), symbol: p.symbol, side: p.type === 0 ? "sell" : "buy", quantity: String(p.volume), request_key: `close-${crypto.randomUUID()}`, expires_at: new Date(Date.now() + 60000).toISOString(), strategy_revision: "operator-close-v1" };
      const intent = await forexRequest<ForexIntent>(`${path}/intents`, order);
      await forexRequest(`${path}/intents/${intent.id}/submit`, {});
      const current = await refresh(); setAccount(current.current.data);
    })}>{l("Close managed position", "Đóng vị thế của ứng dụng")}</button> : <span>{l("Managed in broker terminal", "Quản lý trong terminal broker")}</span>}</div>)}</div>}
    <p className="text-xs text-muted-foreground">{l("SL/TP stays at the broker when stopped. No automatic restart after app/server exit. Confidence is the model's own estimate.", "SL/TP vẫn ở broker khi dừng. Không tự khởi động lại sau khi đóng ứng dụng/server. Độ tin cậy là ước lượng của model.")}</p>
  </section>;
}
