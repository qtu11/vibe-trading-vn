import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowDownRight, ArrowUpRight, Clock3, Users } from "lucide-react";
import type { ForexTradePlan } from "@/lib/forexTradePlan";
import { ForexEvidence } from "@/components/forex/ForexEvidence";
import { ForexPlanChart } from "@/components/forex/ForexPlanChart";
import { ForexTrendForecast } from "@/components/forex/ForexTrendForecast";
import { ForexCouncilUsage } from "@/components/forex/ForexCouncilUsage";

export function ForexTradeCards({ plan }: { plan: ForexTradePlan }) {
  const { i18n } = useTranslation();
  const vi = i18n.language.startsWith("vi");
  const l = (en: string, vn: string) => vi ? vn : en;
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [plan.plan_id]);
  const expired = now >= Date.parse(plan.expires_at);
  const ready = plan.status === "ready" && !expired;
  const roles: Record<string, string> = {
    technical: l("Technical analyst", "Phân tích kỹ thuật"), macro: l("Macro analyst", "Phân tích vĩ mô"),
    bull: l("BUY case", "Luận điểm BUY"), bear: l("SELL case", "Luận điểm SELL"),
    risk: l("Risk critic", "Phản biện rủi ro"), manager: l("Synthesis", "Tổng hợp kết luận"),
  };
  const reasons: Record<string, string> = {
    DATA_OR_BROKER_CONSTRAINTS_INCOMPLETE: l("History, quote or broker constraints are incomplete.", "Lịch sử, báo giá hoặc quy tắc broker chưa đủ điều kiện."),
    COUNCIL_MODEL_UNAVAILABLE: l("Configured model is unavailable.", "Model được cấu hình chưa hoạt động."),
    COUNCIL_ROLE_FAILED_OR_INVALID: l("A role failed or returned invalid evidence references.", "Có vai trò lỗi hoặc trích dẫn bằng chứng không hợp lệ."),
    COUNCIL_CANCELLED_OR_TIMED_OUT: l("Analysis was cancelled or exceeded its time budget.", "Phân tích bị hủy hoặc vượt thời gian cho phép."),
    RISK_REVIEW_WAIT_OR_VETO: l("The risk critic requires waiting or vetoed entry.", "Vai trò rủi ro yêu cầu chờ hoặc phủ quyết vào lệnh."),
    PRICE_MOVED_REANALYZE: l("Price moved beyond the reviewed range; reanalyze.", "Giá đã dịch chuyển quá phạm vi được đánh giá; cần phân tích lại."),
    FINAL_QUOTE_OR_CONSTRAINTS_INVALID: l("A fresh final broker quote could not be validated.", "Chưa xác thực được báo giá broker mới nhất."),
    ENTRY_TIMING_NOT_APPROVED: l("Requested MARKET/LIMIT timing did not pass the risk review.", "Thời điểm MARKET/LIMIT chưa được vòng rủi ro chấp thuận."),
  };
  const utc = (value: string | undefined | null) => {
    if (!value) return "—";
    try {
      const d = new Date(value);
      if (isNaN(d.getTime())) return String(value);
      return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");
    } catch {
      return String(value);
    }
  };
  const manager = plan.reports.find(r => r.role === "manager");
  return <section aria-label={l("Forex trade scenarios", "Kịch bản giao dịch Forex")} className="my-3 space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
      <strong>{plan.symbol} · {ready ? `${l("Preferred", "Ưu tiên")} ${plan.recommendation.toUpperCase()}` : expired ? l("EXPIRED · reanalyze", "HẾT HẠN · cần phân tích lại") : l("WAIT · no entry recommendation", "CHỜ · chưa khuyến nghị vào lệnh")}</strong>
      <span className="text-xs text-muted-foreground">MT5 · {plan.broker_server} · {plan.environment.toUpperCase()}</span>
    </div>
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {(["buy", "sell"] as const).map(side => {
        const s = plan.scenarios.find(s => s.side === side);
        const selected = ready && plan.recommendation === side;
        const buy = side === "buy";
        const Arrow = buy ? ArrowUpRight : ArrowDownRight;
        return <article key={side} aria-label={`${side.toUpperCase()} ${plan.symbol}`}
          className={`rounded-xl border p-4 ${buy ? "border-emerald-500/60 bg-emerald-50 dark:bg-emerald-950/30" : "border-red-500/60 bg-red-50 dark:bg-red-950/30"}`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className={`flex items-center gap-1 text-lg font-bold ${buy ? "text-emerald-800 dark:text-emerald-300" : "text-red-800 dark:text-red-300"}`}><Arrow size={20} aria-hidden="true" />{side.toUpperCase()}</h3>
            <span className="rounded-full border bg-background/70 px-2 py-1 text-xs font-medium">{selected ? l("Preferred scenario", "Kịch bản ưu tiên") : expired ? l("Expired", "Đã hết hạn") : l("Conditional · not selected", "Có điều kiện · chưa chọn")}</span>
          </div>
          <p className="mt-2 text-sm font-semibold">{s ? s.order_type === "market"
            ? l("MARKET · immediate entry proposal", "MARKET · đề xuất mở ngay")
            : l("LIMIT · wait for entry price", "LIMIT · chờ giá vào lệnh")
            : l("Order type unavailable", "Chưa có loại lệnh hợp lệ")}</p>
          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-3 text-sm">
            <div className="col-span-2"><dt className="text-xs text-muted-foreground">{l("Entry reference", "Giá vào tham chiếu")} · {plan.currency}</dt><dd className="mt-0.5 font-mono text-2xl font-semibold tabular-nums">{s?.entry ?? "—"}</dd></div>
            <div><dt className="text-xs text-muted-foreground">{l("Stop loss", "Cắt lỗ")} · SL</dt><dd className="font-mono font-medium tabular-nums">{s?.stop_loss ?? "—"}</dd></div>
            <div><dt className="text-xs text-muted-foreground">{l("Take profit", "Chốt lời")} · TP</dt><dd className="font-mono font-medium tabular-nums">{s?.take_profit ?? "—"}</dd></div>
            <div className="col-span-2 text-xs text-muted-foreground">{l("Reward / risk", "Lợi nhuận / rủi ro")}: {s ? `${Number(s.reward_risk).toFixed(2)} : 1` : "—"}</div>
          </dl>
          <p className="mt-3 text-xs leading-relaxed">{expired ? l("Reanalyze before using these levels.", "Phân tích lại trước khi dùng các mức giá này.")
            : selected ? s?.order_type === "limit" ? l("Only consider entry if the limit is reached while the thesis remains valid.", "Chỉ xem xét vào khi giá chạm limit và luận điểm còn hiệu lực.")
              : l("Reference price may change; execution requires a fresh broker check.", "Giá tham chiếu có thể đổi; cần kiểm tra broker mới trước thực thi.")
            : l("Alternative scenario only. Do not open both directions from these cards.", "Kịch bản đối ứng để theo dõi; chưa có tín hiệu chọn hướng này.")}</p>
        </article>;
      })}
    </div>
    <ForexTrendForecast plan={plan} />
    {plan.connection_id && <ForexPlanChart connectionId={plan.connection_id} symbol={plan.symbol} />}
    {manager && <p className="text-sm leading-relaxed">{manager.summary}</p>}
    {plan.reasons.length > 0 && <ul className="space-y-1 text-xs text-muted-foreground">{plan.reasons.map(r => <li key={r}>{reasons[r] || r}</li>)}</ul>}
    <p className="text-xs text-muted-foreground">Bid <span className="font-mono">{plan.bid}</span> / Ask <span className="font-mono">{plan.ask}</span> {plan.currency}</p>
    <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground"><Clock3 size={13} aria-hidden="true" />{l("Quote", "Báo giá")}: {utc(plan.quote_at)} · {l("Valid until", "Hiệu lực đến")}: {utc(plan.expires_at)}</p>
    {plan.evidence && <ForexEvidence evidence={plan.evidence} />}
    {plan.llm_usage && <ForexCouncilUsage usage={plan.llm_usage} />}
    <details className="rounded-lg border p-3 text-sm">
      <summary className="cursor-pointer font-medium"><Users className="mr-1 inline" size={15} aria-hidden="true" />{l("Analysis & debate", "Phân tích & phản biện")} · {plan.reports.length}/6 {l("roles", "vai trò")} · {plan.unique_models} model</summary>
      <p className="mt-2 text-xs text-muted-foreground">{plan.unique_models === 1 ? l("These roles use the same model in separate calls; this is not independent model consensus.", "Các vai trò gọi riêng cùng một model; đây chưa phải đồng thuận từ nhiều model độc lập.") : l("Model identities are recorded per role below.", "Model thực tế của từng vai trò được ghi bên dưới.")} {l("One bounded critique round. Opinions may be wrong.", "Một vòng phản biện có giới hạn. Nhận định có thể sai.")}</p>
      {plan.failures?.map(f => <p key={f.role} className="mt-2 text-xs text-red-700 dark:text-red-300">{roles[f.role]} · {l("Failed", "Chưa hoàn tất")}: {({
        INVALID_JSON: l("Model did not return valid JSON", "Model không trả JSON hợp lệ"),
        REPORT_TOO_LONG: l("Report exceeded the length limit", "Báo cáo vượt giới hạn độ dài"),
        INVALID_REPORT_SCHEMA: l("Report fields did not satisfy the schema", "Các trường báo cáo không đúng schema"),
        INVALID_EVIDENCE_REFS: l("Evidence references are invalid or incomplete", "Tham chiếu bằng chứng không hợp lệ hoặc chưa đủ"),
        MODEL_REQUEST_FAILED: l("Model request failed or timed out", "Lời gọi model lỗi hoặc hết thời gian"),
      } as Record<string, string>)[f.code] || f.code}</p>)}
      <ol className="mt-3 space-y-3">{plan.reports.map(r => <li key={r.role} className="border-t pt-2">
        <div className="flex flex-wrap justify-between gap-1"><strong>{roles[r.role]}</strong><span className="text-xs">{r.stance.toUpperCase()}{r.veto ? ` · ${r.role === "risk" || r.role === "manager" ? l("VETO", "PHỦ QUYẾT") : l("ADVISES WAIT", "ĐỀ NGHỊ CHỜ")}` : ""}</span></div>
        <p className="mt-1 text-sm">{r.summary}</p><p className="mt-1 text-xs text-muted-foreground">{l("Counterpoint / invalidation", "Phản biện / điều kiện vô hiệu")}: {r.counterargument}</p>
        <p className="mt-1 break-words text-xs text-muted-foreground">{r.provider} / {r.model} · {Array.isArray(r.evidence_refs) ? r.evidence_refs.join(", ") : "—"}</p>
      </li>)}</ol>
      <p className="mt-3 break-all text-xs text-muted-foreground">{l("Evidence snapshot", "Bản chụp bằng chứng")}: {plan.evidence_hash ? plan.evidence_hash.slice(0, 16) : "—"}</p>
    </details>
    <p className="text-xs text-muted-foreground">{l("Calculated research scenarios · no order has been sent. The separate automated trading runner is not started by these cards.", "Kịch bản phân tích có giá tính toán · chưa gửi lệnh. Hai ô này không khởi động runner giao dịch tự động.")}</p>
  </section>;
}
