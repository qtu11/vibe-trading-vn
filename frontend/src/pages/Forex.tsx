import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowLeftRight, KeyRound, Plus, RefreshCw, ShieldAlert } from "lucide-react";
import { ForexConnectionForm, button, field, panel } from "@/components/forex/ForexConnectionForm";
import { ForexOrders } from "@/components/forex/ForexOrders";
import { ForexAutomation } from "@/components/forex/ForexAutomation";
import { ForexAI } from "@/components/forex/ForexAI";
import { ForexMarket } from "@/components/forex/ForexMarket";
import { useSearchParams } from "react-router";
import { forexPath, forexRequest, type ForexConfig, type ForexConnection, type ForexIntent, type ForexRunner } from "@/lib/forexApi";

const secretNames = { mt5: ["password"], exness: ["api_key", "private_key"], oanda: ["token"] } as const;

export function Forex() {
  const [query] = useSearchParams();
  const { i18n } = useTranslation();
  const vi = i18n.language.startsWith("vi");
  const l = (en: string, vietnamese: string) => vi ? vietnamese : en;
  const [connections, setConnections] = useState<ForexConnection[]>([]);
  const [selectedId, setSelectedId] = useState(query.get("connection_id") || "");
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  const [editingNew, setEditingNew] = useState(false);
  const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [intents, setIntents] = useState<ForexIntent[]>([]);
  const [runner, setRunner] = useState<ForexRunner>({ running: false, status: "stopped" });
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [verified, setVerified] = useState<Record<string, unknown> | null>(null);
  const [mcpConfig, setMcpConfig] = useState<Record<string, unknown> | null>(null);
  const selected = useMemo(() => connections.find(c => c.id === selectedId), [connections, selectedId]);
  const loadConnections = useCallback(async () => {
    const response = await forexRequest<{ connections: ForexConnection[] }>("/api/forex/connections");
    setConnections(response.connections);
    if (selectedRef.current && response.connections.some(c => c.id === selectedRef.current)) return;
    // Resolve the native symbol against existing saved sessions using READS.
    // Never switch a terminal login, save credentials or enable execution.
    if (!query.get("connection_id") && response.connections.some(c => c.connector === "mt5")) {
      try {
        const native = await forexRequest<{ _meta: { connection_id: string } }>(
          `/api/forex/market-snapshot?${new URLSearchParams({ symbol: query.get("symbol") || "XAUUSDm", limit: "1" })}`);
        if (!selectedRef.current && response.connections.some(c => c.id === native._meta.connection_id)) {
          setSelectedId(native._meta.connection_id); return;
        }
      } catch { /* Ambiguous/unavailable sessions remain an explicit choice. */ }
    }
    setSelectedId(id => response.connections.some(c => c.id === id) ? id : response.connections[0]?.id || "");
  }, []);
  const loadExecution = useCallback(async () => {
    if (!selectedId) return;
    const [journal, runtime] = await Promise.all([
      forexRequest<{ intents: ForexIntent[] }>(`${forexPath(selectedId)}/intents`),
      forexRequest<ForexRunner>(`${forexPath(selectedId)}/runner`),
    ]);
    if (selectedRef.current === selectedId) { setIntents(journal.intents); setRunner(runtime); }
  }, [selectedId]);
  const reload = useCallback(async () => { await Promise.all([loadConnections(), loadExecution()]); }, [loadConnections, loadExecution]);
  useEffect(() => { void loadConnections().catch(e => setError(String(e.message))); }, [loadConnections]);
  useEffect(() => {
    let active = true;
    setIntents([]); setRunner({ running: false, status: "stopped" }); setSecrets({}); setVerified(null); setMcpConfig(null);
    const poll = () => { if (active) void loadExecution().catch(e => { if (active) setError(String(e.message)); }); };
    poll(); const interval = window.setInterval(poll, 5000);
    return () => { active = false; window.clearInterval(interval); };
  }, [loadExecution]);
  const action = async (fn: () => Promise<void>) => {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const save = async (config: ForexConfig) => action(async () => {
    await forexRequest(forexPath(config.id), config, "PUT");
    await loadConnections(); setSelectedId(config.id); setEditingNew(false);
    setNotice(l("Connection saved. Credentials and verification are separate.", "Đã lưu kết nối. Lưu thông tin đăng nhập và xác minh ở bước riêng."));
  });
  const componentKey = selected ? JSON.stringify(selected) : "new";
  return <div className="mx-auto max-w-6xl space-y-5 p-4 md:p-6">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="flex items-center gap-2 text-xl font-semibold"><ArrowLeftRight className="h-5 w-5 text-primary" />Forex & Brokers</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{l("Account-bound market data and protected execution through MT5, Exness API and OANDA. MT5 can connect to Exness, IC Markets, Pepperstone, FxPro and other compatible brokers.", "Dữ liệu và thực thi gắn đúng tài khoản qua MT5, Exness API và OANDA. MT5 có thể kết nối Exness, IC Markets, Pepperstone, FxPro và các broker tương thích khác.")}</p></div>
      <div className="flex flex-wrap gap-2"><button className={button} disabled={busy} onClick={() => void action(async () => {
        const result = await forexRequest<{ connections: ForexConfig[]; issues: { error: string }[] }>("/api/forex/mt5/auto-connect", {});
        await loadConnections();
        if (result.connections.length) { setSelectedId(result.connections[0].id); setEditingNew(false); }
        setNotice(result.connections.length ? l("Attached to the logged-in MT5 session. No password needed; execution settings remain explicit.", "Đã nối phiên MT5 đang đăng nhập, không cần nhập mật khẩu. Quyền thực thi theo cấu hình riêng.") : result.issues.map(i => i.error).join("; ") || l("Open and log in to MT5 first.", "Mở MT5 và đăng nhập trước."));
      })}>{l("Connect running MT5", "Tự kết nối MT5 đang mở")}</button><button className={button} disabled={busy} onClick={() => void action(reload)} aria-label={l("Refresh forex state", "Cập nhật trạng thái forex")}><RefreshCw className="h-4 w-4" /></button><button className={`${button} flex items-center gap-1`} disabled={busy} onClick={() => { setEditingNew(true); setError(""); setNotice(""); }}><Plus className="h-4 w-4" />{l("Add connection", "Thêm kết nối")}</button></div>
    </header>
    {error && <div role="alert" className="flex gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive"><ShieldAlert className="h-4 w-4 shrink-0" />{error}</div>}
    {notice && <p role="status" className="rounded-lg border p-3 text-sm">{notice}</p>}
    {connections.length > 0 && <div className="flex flex-wrap items-center gap-3 rounded-xl border p-3">
      <label className="min-w-52 flex-1 text-xs">{l("Selected account", "Tài khoản đang chọn")}<select className={`${field} mt-1`} disabled={busy} value={selectedId} onChange={e => { setSelectedId(e.target.value); setEditingNew(false); setError(""); setNotice(""); }}>{connections.map(c => <option key={c.id} value={c.id}>{c.label} · {c.account_ref} · {c.environment.toUpperCase()}</option>)}</select></label>
      {selected && <><span className={`rounded-full border px-3 py-1 text-xs font-semibold ${selected.environment === "live" ? "border-amber-500/40 text-amber-500" : "text-primary"}`}>{selected.environment.toUpperCase()}</span><span className="text-xs text-muted-foreground">{selected.halted ? l("Trading halted", "Đang dừng giao dịch") : selected.execution_enabled ? l("Execution configured; per-order checks required", "Đã bật thực thi; vẫn kiểm tra từng lệnh") : l("Read only", "Chỉ đọc")}</span></>}
    </div>}
    {(editingNew || !connections.length) && <ForexConnectionForm key="create" onSave={save} />}
    {selected && !editingNew && <>
      <ForexMarket key={componentKey+"market"} connection={selected} initialSymbol={query.get("symbol") || ""} />
      <ForexAI key={componentKey+"ai"} connection={selected} runner={runner} reload={reload} onError={setError} />
      <section className={panel}>
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="flex items-center gap-2 font-semibold"><KeyRound className="h-4 w-4" />{l("Credentials & account verification", "Thông tin đăng nhập & xác minh")}</h2>
          <div className="flex flex-wrap gap-2"><button className={button} disabled={busy} onClick={() => void action(async () => {
            const data = await forexRequest<{ account: Record<string, unknown> }>(`${forexPath(selected.id)}/verify`, {}); setVerified(data.account);
            setNotice(l("Broker identity verified for this account.", "Đã xác minh danh tính tài khoản từ broker."));
          })}>{l("Verify account", "Xác minh tài khoản")}</button>
          <button className={`${button} text-destructive`} disabled={busy} onClick={() => void action(async () => { await forexRequest(`${forexPath(selected.id)}/halt`, {}); await reload(); })}>{l("Halt connection", "Dừng khẩn cấp kết nối")}</button>
          <button className={button} disabled={busy || !selected.connection_halted} onClick={() => void action(async () => { await forexRequest(`${forexPath(selected.id)}/resume`, {}); await reload(); })}>{l("Resume connection", "Gỡ dừng kết nối")}</button>
          {selected.broker_halted && <button className={button} disabled={busy} onClick={() => void action(async () => { await forexRequest(`${forexPath(selected.id)}/resume-broker`, {}); await reload(); })}>{l(`Resume ${selected.connector.toUpperCase()} after reconciliation`, `Gỡ dừng ${selected.connector.toUpperCase()} sau đối soát`)}</button>}</div>
        </div>
        {selected.session_mode !== "existing_terminal" && <p className="break-all font-mono text-xs text-muted-foreground">{selected.credential_ref}</p>}
        {selected.global_halted && <p role="status" className="text-sm text-amber-600">{l("Global trading halt is active. Review it in Trading status before resuming.", "Đang có dừng giao dịch toàn cục. Kiểm tra tại Trạng thái giao dịch trước khi tiếp tục.")}</p>}
        <p className="text-xs text-muted-foreground">{l("Halt and stop prevent new orders; existing broker positions and SL/TP remain active. Manage existing positions in the broker terminal.", "Dừng kết nối hoặc chiến lược chặn lệnh mới; vị thế và SL/TP tại broker vẫn hoạt động. Quản lý vị thế hiện có trong terminal của broker.")}</p>
        {selected.connector === "mt5" && selected.session_mode === "existing_terminal" ? <p className="text-sm">{l("Using the existing MT5 login. The application checks account, server and demo/live identity on every operation; no account password is read or stored.", "Đang dùng phiên MT5 đã đăng nhập. Ứng dụng kiểm tra lại tài khoản, server và Demo/Live ở mỗi thao tác; không đọc hoặc lưu mật khẩu tài khoản.")}</p> : <form className="space-y-3" onSubmit={e => { e.preventDefault(); void action(async () => {
          await forexRequest(`${forexPath(selected.id)}/credentials`, secrets); setSecrets({});
          setNotice(l("Credentials saved in the OS vault. They are not returned to the browser or MCP.", "Đã lưu vào kho bí mật hệ điều hành. Giá trị không được đọc trả lại trình duyệt hoặc MCP."));
        }); }}>
          <div className="grid gap-3 sm:grid-cols-2">{secretNames[selected.connector].map(name => <label className={`space-y-1 text-xs ${name === "private_key" ? "sm:col-span-2" : ""}`} key={name}>{name === "password" ? l("MT5 account password", "Mật khẩu tài khoản MT5") : name}
            {name === "private_key" ? <textarea className={`${field} min-h-24 font-mono`} autoComplete="off" value={secrets[name] || ""} onChange={e => setSecrets(s => ({ ...s, [name]: e.target.value }))} placeholder="Ed25519 PKCS8 PEM / Exness 128-character hex" />
              : <input className={field} type="password" autoComplete="new-password" value={secrets[name] || ""} onChange={e => setSecrets(s => ({ ...s, [name]: e.target.value }))} />}</label>)}</div>
          <button className={button} disabled={busy || !Object.values(secrets).some(Boolean)}>{l("Save credentials", "Lưu thông tin đăng nhập")}</button>
        </form>}
        {verified && <dl className="grid grid-cols-2 gap-3 rounded-lg bg-muted/40 p-3 sm:grid-cols-4">{["account_ref", "currency", "equity", "free_margin"].map(k => <div key={k}><dt className="text-xs text-muted-foreground">{k}</dt><dd className="break-all font-mono text-sm">{verified[k] === null || verified[k] === undefined ? "—" : String(verified[k])}</dd></div>)}</dl>}
      </section>
      <div className="grid items-start gap-5 xl:grid-cols-2"><div className="space-y-5"><ForexOrders key={componentKey+"orders"} connection={selected} intents={intents} reload={reload} onError={setError} /><ForexAutomation key={componentKey+"runner"} connection={selected} status={runner} reload={reload} onError={setError} /></div>
        <div className="space-y-5"><ForexConnectionForm key={componentKey+"settings"} connection={selected} onSave={save} />
          <details className={panel}><summary className="cursor-pointer text-sm font-medium">MCP</summary><p className="text-xs text-muted-foreground">{l("Local stdio config for this saved connection. Read-only by default. Add --allow-execution only for an operator-authorized connection.", "Cấu hình stdio cục bộ cho kết nối đã lưu. Mặc định chỉ đọc. Chỉ thêm --allow-execution khi operator đã cấp quyền.")}</p>
            <button className={button} disabled={busy} onClick={() => void action(async () => setMcpConfig(await forexRequest<Record<string, unknown>>(`${forexPath(selected.id)}/mcp-config`)))}>{l("Generate config for this computer", "Tạo cấu hình cho máy này")}</button>
            {mcpConfig && <pre className="overflow-x-auto rounded-md bg-muted p-3 text-[11px]">{JSON.stringify(mcpConfig, null, 2)}</pre>}
            <p className="text-xs text-muted-foreground">{l("The API and runner require configured broker access. No connected account is implied by the presence of this page.", "API và runner cần quyền truy cập broker đã cấu hình. Trang này không tự xác nhận đã có kết nối broker.")}</p>
          </details></div></div>
    </>}
  </div>;
}
