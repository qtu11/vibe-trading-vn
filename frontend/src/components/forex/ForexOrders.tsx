import { useState } from "react";
import { useTranslation } from "react-i18next";
import { forexPath, forexRequest, type ForexConnection, type ForexOrder, type ForexIntent } from "@/lib/forexApi";
import { button, field, panel } from "./ForexConnectionForm";

const show = (value: unknown) => value === null || value === undefined ? "—" : String(value);

export function ForexOrders({ connection, intents, reload, onError }: {
  connection: ForexConnection; intents: ForexIntent[]; reload: () => Promise<void>; onError: (message: string) => void;
}) {
  const { i18n } = useTranslation();
  const l = (en: string, vi: string) => i18n.language.startsWith("vi") ? vi : en;
  const [symbol, setSymbol] = useState(connection.symbols[0] || "");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [quantity, setQuantity] = useState(connection.limits.max_quantity);
  const [stop, setStop] = useState(""); const [take, setTake] = useState("");
  const [quote, setQuote] = useState<Record<string, unknown> | null>(null);
  const [catalog, setCatalog] = useState<Record<string, unknown>[]>([]);
  const [plan, setPlan] = useState<ForexOrder | null>(null);
  const [assessment, setAssessment] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false); const [liveAck, setLiveAck] = useState(false);
  const [references, setReferences] = useState<Record<string, string>>({});
  const invalidate = () => { setPlan(null); setAssessment(null); };
  const action = async (fn: () => Promise<void>) => {
    setBusy(true); onError("");
    try { await fn(); } catch (e) { onError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const preview = () => action(async () => {
    const order: ForexOrder = { symbol, side, quantity, stop_loss: stop, take_profit: take || null,
      request_key: `manual-${crypto.randomUUID()}`, expires_at: new Date(Date.now() + 180000).toISOString(), strategy_revision: "manual-v1" };
    const result = await forexRequest<{ assessment: Record<string, unknown> }>(`${forexPath(connection.id)}/preview`, order);
    setAssessment(result.assessment); setPlan(order);
  });
  const send = () => action(async () => {
    if (!plan) return;
    const intent = await forexRequest<ForexIntent>(`${forexPath(connection.id)}/intents`, plan);
    // No automatic retry here, even when the request times out.
    try { await forexRequest(`${forexPath(connection.id)}/intents/${intent.id}/submit`, {}); }
    finally { invalidate(); await reload(); }
  });
  return <>
    <section className={panel}>
      <div><h2 className="font-semibold">{l("Broker data & protected order", "Dữ liệu broker & lệnh có bảo vệ")}</h2>
        <p className="mt-1 text-xs text-muted-foreground">{l("Exact native symbols. Quantities are lots on MT5, units on OANDA and instrument volume on Exness API.", "Dùng đúng symbol broker. Khối lượng là lot trên MT5, unit trên OANDA và volume theo instrument trên Exness API.")}</p></div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-40 flex-1 space-y-1 text-xs">Symbol<input className={field} value={symbol} list="forex-catalog" onChange={e => { setSymbol(e.target.value); invalidate(); setQuote(null); }} /></label>
        <datalist id="forex-catalog">{catalog.map(row => { const name = show(row.symbol ?? row.instrument ?? row.name); return <option key={name} value={name} />; })}</datalist>
        <button className={button} disabled={busy || !symbol} onClick={() => void action(async () => {
          const response = await forexRequest<{ data: Record<string, unknown> }>(`${forexPath(connection.id)}/quote?symbol=${encodeURIComponent(symbol)}`); setQuote(response.data);
        })}>{l("Get quote", "Lấy quote")}</button>
        <button className={button} disabled={busy} onClick={() => void action(async () => {
          const response = await forexRequest<{ data: Record<string, unknown>[] }>(`${forexPath(connection.id)}/instruments?limit=300`); setCatalog(response.data);
        })}>{l("Load instruments", "Tải danh mục")}</button>
      </div>
      {quote && <dl className="grid gap-3 rounded-lg bg-muted/40 p-3 sm:grid-cols-3">
        <div><dt className="text-xs text-muted-foreground">Bid / Ask</dt><dd className="font-mono text-sm">{show(quote.bid)} / {show(quote.ask)}</dd></div>
        <div><dt className="text-xs text-muted-foreground">{l("Broker UTC time", "Thời gian UTC từ broker")}</dt><dd className="break-all text-xs">{show(quote.timestamp)}</dd></div>
        <div><dt className="text-xs text-muted-foreground">{l("Source", "Nguồn")}</dt><dd className="text-sm">{show(quote.source)}</dd></div>
      </dl>}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <label className="space-y-1 text-xs">{l("Side", "Chiều lệnh")}<select className={field} value={side} onChange={e => { setSide(e.target.value as "buy" | "sell"); invalidate(); }}><option value="buy">BUY</option><option value="sell">SELL</option></select></label>
        <label className="space-y-1 text-xs">{l("Quantity", "Khối lượng")}<input className={field} inputMode="decimal" value={quantity} onChange={e => { setQuantity(e.target.value); invalidate(); }} /></label>
        <label className="space-y-1 text-xs">Stop loss<input className={field} inputMode="decimal" value={stop} onChange={e => { setStop(e.target.value); invalidate(); }} /></label>
        <label className="space-y-1 text-xs">Take profit<input className={field} inputMode="decimal" value={take} onChange={e => { setTake(e.target.value); invalidate(); }} /></label>
      </div>
      {assessment && <dl className="grid grid-cols-3 gap-2 rounded-lg border p-3 text-xs">{["notional_usd", "stop_risk_usd", "estimated_margin"].map(key => <div key={key}><dt className="text-muted-foreground">{({ notional_usd: "Notional USD", stop_risk_usd: "Stop risk USD", estimated_margin: "Margin estimate USD" })[key]}</dt><dd className="mt-1 font-mono text-sm">{show(assessment[key])}</dd></div>)}</dl>}
      {connection.environment === "live" && <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={liveAck} onChange={e => setLiveAck(e.target.checked)} /><span>{l("This is the selected LIVE account. I intend to submit the previewed order within its mandate.", "Đây là tài khoản LIVE đã chọn. Tôi muốn gửi lệnh đã xem trong phạm vi mandate.")}</span></label>}
      <div className="flex flex-wrap gap-2"><button className={button} disabled={busy || !symbol || !stop} onClick={() => void preview()}>{l("Preview risk", "Xem rủi ro")}</button>
        <button className={`${button} bg-primary text-primary-foreground`} disabled={busy || !plan || !connection.execution_enabled || connection.halted || (connection.environment === "live" && !liveAck)} onClick={() => void send()}>{l("Submit protected order", "Gửi lệnh có bảo vệ")}</button></div>
      {!connection.execution_enabled && <p className="text-xs text-muted-foreground">{l("Read-only connection. Enable execution in settings before submitting.", "Kết nối chỉ đọc. Bật thực thi trong cấu hình trước khi gửi lệnh.")}</p>}
    </section>
    <section className={panel}><h2 className="font-semibold">{l("Execution journal", "Nhật ký thực thi")}</h2>
      {!intents.length ? <p className="text-sm text-muted-foreground">{l("No forex intents recorded for this connection.", "Chưa có intent nào trên kết nối này.")}</p> : <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr className="border-b text-muted-foreground"><th className="py-2">Intent</th><th>Symbol</th><th>{l("State", "Trạng thái")}</th><th /></tr></thead>
      <tbody>{intents.map(row => <tr key={row.id} className="border-b align-top"><td className="max-w-36 py-3 font-mono" title={row.id}>{row.id.slice(0, 15)}…</td><td className="py-3">{row.payload.symbol}<span className="block text-muted-foreground">{row.payload.side} {row.payload.quantity}</span></td><td className="py-3"><span className="rounded bg-muted px-2 py-1 font-mono">{row.state}</span>{Boolean(row.result.error) && <p className="mt-2 max-w-72 text-destructive">{show(row.result.error)}</p>}</td><td className="space-y-2 py-2 text-right">{["submitting", "accepted", "working", "partial", "unknown"].includes(row.state) && <button className={button} disabled={busy} onClick={() => void action(async () => { await forexRequest(`${forexPath(connection.id)}/intents/${row.id}/reconcile`, {}); await reload(); })}>{l("Reconcile", "Đối soát")}</button>}
        {connection.connector === "exness" && ["submitting", "unknown"].includes(row.state) && !row.result.operation_id && <details className="max-w-56 text-left"><summary className="cursor-pointer text-xs">{l("Recover a lost ACK", "Khôi phục ACK bị mất")}</summary><label className="mt-2 block space-y-1">{l("Operation ID from broker evidence", "Operation ID từ bằng chứng broker")}<input className={field} value={references[row.id] || ""} maxLength={128} onChange={e => setReferences(r => ({ ...r, [row.id]: e.target.value }))} /></label><button className={`${button} mt-2`} disabled={busy || !references[row.id]} onClick={() => void action(async () => { await forexRequest(`${forexPath(connection.id)}/intents/${row.id}/operation-reference`, { operation_id: references[row.id] }); await reload(); })}>{l("Verify broker reference", "Xác minh mã đối chiếu")}</button><p className="mt-2 text-muted-foreground">{l("The broker must return this intent's exact client request ID. No manual filled override.", "Broker phải trả đúng client request ID của intent. Không sửa trạng thái khớp bằng tay.")}</p></details>}
      </td></tr>)}</tbody></table></div>}
      <p className="text-xs text-muted-foreground">{l("Accepted/confirmed do not mean a fill. Unknown executions stay blocked until broker evidence resolves them. Never retry a timed-out order with a new key.", "Accepted/confirmed không đồng nghĩa đã khớp. Kết quả unknown bị chặn đến khi có bằng chứng broker. Không gửi lại lệnh timeout bằng key mới.")}</p>
    </section>
  </>;
}
