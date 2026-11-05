import { useTranslation } from "react-i18next";
import type { ForexCouncilUsage as Usage } from "@/lib/forexTradePlan";

export function ForexCouncilUsage({ usage }: { usage: Usage }) {
  const { i18n } = useTranslation();
  const vi = i18n.language.startsWith("vi");
  const l = (en: string, vn: string) => vi ? vn : en;
  const n = (value?: number) => value == null ? "—" : value.toLocaleString(vi ? "vi-VN" : "en-US");
  return <details className="rounded-lg border p-3 text-xs">
    <summary className="cursor-pointer font-medium">{l("Council token usage", "Token của hội đồng AI")} · {usage.reported_calls}/{usage.attempted_calls} {l("calls reported", "lời gọi có usage")}</summary>
    <p className="mt-2">Input {n(usage.totals?.input_tokens)} · Output {n(usage.totals?.output_tokens)} · Cache {n(usage.totals?.cache_read_tokens)}</p>
    {usage.missing_calls > 0 && <p className="mt-1 text-amber-700 dark:text-amber-400">{usage.missing_calls} {l("calls have unknown usage. These totals include reported calls only.", "lời gọi chưa có usage. Tổng trên chỉ gồm phần provider đã báo.")}</p>}
    <ul className="mt-2 space-y-1">{usage.per_role.map(r => <li key={r.role}>{r.role}: ↑{n(r.usage?.input_tokens)} ↓{n(r.usage?.output_tokens)}</li>)}</ul>
    <p className="mt-2 text-muted-foreground">{l("Cached tokens are a subset of input, not extra tokens or a monetary bill. Raw OHLC is sent to technical once; other roles receive computed evidence and prior reports. The six calls still consume tokens.", "Cache đã nằm trong input, không phải token cộng thêm hoặc số tiền thanh toán. Chỉ technical nhận OHLC thô; các vai trò khác dùng bằng chứng đã tính và báo cáo trước đó. Sáu lời gọi vẫn tiêu thụ token.")}</p>
  </details>;
}
