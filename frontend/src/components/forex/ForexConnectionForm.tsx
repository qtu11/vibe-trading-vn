import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { editableForex, type ForexConfig, type ForexConnection, type ForexLimits } from "@/lib/forexApi";

export const field = "w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20";
export const button = "rounded-md border px-3 py-2 text-sm font-medium hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-40 disabled:cursor-not-allowed";
export const panel = "rounded-xl border bg-card p-4 md:p-5 space-y-4";

export function ForexConnectionForm({ connection, onSave }: { connection?: ForexConnection; onSave: (config: ForexConfig) => Promise<void> }) {
  const { i18n } = useTranslation();
  const l = (en: string, vi: string) => i18n.language.startsWith("vi") ? vi : en;
  const [config, setConfig] = useState(() => editableForex(connection));
  const [symbolsText, setSymbolsText] = useState(config.symbols.join(", "));
  const [hostsText, setHostsText] = useState(config.allowed_hosts.join(", "));
  const [busy, setBusy] = useState(false);
  const change = <K extends keyof ForexConfig>(key: K, value: ForexConfig[K]) => setConfig(c => ({ ...c, [key]: value }));
  const limitLabels: Record<keyof ForexLimits, string> = {
    max_order_notional_usd: l("Max order notional (USD)", "Notional tối đa mỗi lệnh (USD)"),
    max_total_exposure_usd: l("Max gross exposure (USD)", "Tổng exposure tối đa (USD)"),
    max_stop_risk_usd: l("Max estimated stop risk (USD)", "Rủi ro ước tính tại stop (USD)"),
    max_equity_drawdown_usd: l("Max drawdown from observed equity peak (USD)", "Sụt giảm tối đa từ đỉnh equity đã quan sát (USD)"),
    max_quantity: l("Max quantity (MT5 lots / OANDA units)", "Khối lượng tối đa (lot MT5 / unit OANDA)"),
    max_spread_points: l("Max spread (broker points)", "Spread tối đa (point broker)"),
    max_leverage: l("Max gross exposure / equity", "Tỷ lệ exposure / equity tối đa"),
    max_deviation_points: l("Max requested deviation (points)", "Deviation yêu cầu tối đa (point)"),
    max_quote_age_seconds: l("Max quote age (seconds)", "Tuổi quote tối đa (giây)"),
    max_orders_per_day: l("Max submissions per UTC day", "Số lần gửi tối đa mỗi ngày UTC"),
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true);
    try { await onSave(config); } finally { setBusy(false); }
  };
  return <form className={panel} onSubmit={submit}>
    <h2 className="font-semibold">{l("Connection settings", "Cấu hình kết nối")}</h2>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="space-y-1 text-xs">ID<input required className={field} value={config.id} disabled={Boolean(connection)} pattern={"[a-z0-9][a-z0-9._\\-]*"} maxLength={58} onChange={e => change("id", e.target.value)} /></label>
      <label className="space-y-1 text-xs">{l("Label", "Tên hiển thị")}<input required className={field} value={config.label} onChange={e => change("label", e.target.value)} /></label>
      <label className="space-y-1 text-xs">{l("Platform", "Nền tảng")}<select className={field} disabled={connection?.identity_locked} value={config.connector} onChange={e => {
        const connector = e.target.value as ForexConfig["connector"];
        setSymbolsText("");
        setConfig(c => ({ ...c, connector, execution_enabled: false, environment: connector === "exness" ? "live" : "demo",
          symbols: [], limits: { ...c.limits, max_quantity: connector === "oanda" ? "100" : "0.01" } }));
      }}><option value="mt5">MetaTrader 5</option><option value="exness">Exness Trading API</option><option value="oanda">OANDA v20</option></select></label>
      <label className="space-y-1 text-xs">{l("Account ID / login", "Account ID / số login")}<input required disabled={connection?.identity_locked} autoComplete="off" className={field} value={config.account_ref} onChange={e => change("account_ref", e.target.value)} /></label>
      <label className="space-y-1 text-xs">{l("Environment", "Môi trường")}<select className={field} disabled={config.connector === "exness" || connection?.identity_locked} value={config.environment} onChange={e => change("environment", e.target.value as "demo" | "live")}><option value="demo">DEMO / PRACTICE</option><option value="live">LIVE</option></select></label>
      <label className="space-y-1 text-xs">{l("Allowed native symbols (comma-separated)", "Symbol broker được phép (cách nhau bằng dấu phẩy)")}<input className={field} value={symbolsText} onChange={e => { setSymbolsText(e.target.value); change("symbols", e.target.value.split(",").map(v => v.trim()).filter(Boolean)); }} /></label>
      {config.connector === "mt5" && <>
        <label className="space-y-1 text-xs sm:col-span-2">{l("MT5 session", "Phiên MT5")}<select className={field} value={config.session_mode || "credentials"} onChange={e => change("session_mode", e.target.value as "credentials" | "existing_terminal")}><option value="credentials">{l("Account password in OS vault", "Mật khẩu tài khoản trong kho hệ điều hành")}</option><option value="existing_terminal">{l("Attach to logged-in terminal (no password)", "Dùng terminal đang đăng nhập (không cần mật khẩu)")}</option></select></label>
        <label className="space-y-1 text-xs sm:col-span-2">{l("Exact terminal64.exe path", "Đường dẫn chính xác tới terminal64.exe")}<input required disabled={connection?.identity_locked} className={field} value={config.terminal_path} onChange={e => change("terminal_path", e.target.value)} /></label>
        <label className="space-y-1 text-xs sm:col-span-2">{l("Exact broker server", "Server chính xác từ broker")}<input required disabled={connection?.identity_locked} className={field} value={config.server} onChange={e => change("server", e.target.value)} /></label>
      </>}
      {config.connector === "exness" && <>
        <p className="text-xs text-muted-foreground sm:col-span-2">{l("For eligible Exness platform accounts. For an Exness MT5 demo, choose MetaTrader 5.", "Dành cho tài khoản nền tảng Exness có quyền API. Với tài khoản Exness MT5 demo, chọn MetaTrader 5.")}</p>
        <label className="space-y-1 text-xs sm:col-span-2">Gateway HTTPS URL<input required type="url" className={field} value={config.gateway_url} onChange={e => change("gateway_url", e.target.value)} /></label>
        <label className="space-y-1 text-xs sm:col-span-2">{l("Approved Gateway and Access Point hosts", "Hostname Gateway và Access Point đã xác minh")}<input required className={field} value={hostsText} onChange={e => { setHostsText(e.target.value); change("allowed_hosts", e.target.value.split(",").map(v => v.trim()).filter(Boolean)); }} /></label>
      </>}
    </div>
    {connection?.identity_locked && <p className="text-xs text-muted-foreground">{l("Execution history locks this account identity. Add a new connection for another account or terminal.", "Lịch sử lệnh khóa danh tính tài khoản này. Thêm kết nối mới khi đổi tài khoản hoặc terminal.")}</p>}
    <details className="rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">{l("Execution limits", "Giới hạn thực thi")}</summary>
      <p className="my-2 text-xs text-muted-foreground">{l("Application limits apply on demo and live. Execution currently requires USD accounts; Exness API execution also requires USD-quoted instruments.", "Giới hạn áp dụng cả demo và live. Thực thi hiện cần tài khoản USD; Exness API còn cần instrument định giá bằng USD.")}</p>
      <div className="grid gap-3 sm:grid-cols-2">{(Object.keys(limitLabels) as (keyof ForexLimits)[]).map(key => <label key={key} className="space-y-1 text-xs">{limitLabels[key]}<input required className={field} type="number" min={key === "max_deviation_points" ? 0 : typeof config.limits[key] === "number" ? 1 : 0.00000001} step={typeof config.limits[key] === "number" ? "1" : "any"} value={config.limits[key]} onChange={e => setConfig(c => ({ ...c, limits: { ...c.limits, [key]: typeof c.limits[key] === "number" ? Number(e.target.value) : e.target.value } }))} /></label>)}</div>
    </details>
    <label className="flex items-start gap-2 text-sm"><input className="mt-1" type="checkbox" checked={config.execution_enabled} onChange={e => change("execution_enabled", e.target.checked)} /><span>{l("Enable protected execution for this connection", "Cho phép thực thi có kiểm soát trên kết nối này")}<span className="block text-xs text-muted-foreground">{l("Live still requires a separate account-bound mandate. Saving settings never starts a runner.", "Live vẫn cần mandate riêng gắn đúng tài khoản. Lưu cấu hình không khởi động runner.")}</span></span></label>
    <button type="submit" disabled={busy} className={`${button} bg-primary text-primary-foreground`}>{busy ? l("Saving…", "Đang lưu…") : l("Save connection", "Lưu kết nối")}</button>
  </form>;
}
