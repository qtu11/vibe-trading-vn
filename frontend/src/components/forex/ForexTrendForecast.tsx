import { useTranslation } from "react-i18next";
import { forexFrameLabel } from "@/lib/forexChart";
import type { ForexTradePlan } from "@/lib/forexTradePlan";

export function ForexTrendForecast({ plan }: { plan: ForexTradePlan }) {
  const { i18n } = useTranslation();
  const vi = i18n.language.startsWith("vi");
  const l = (en: string, vn: string) => vi ? vn : en;
  const forecast = plan.reports.find(r => r.role === "manager")?.forecast;
  if (!forecast) return null;
  const names = { up: l("Up", "Tăng"), down: l("Down", "Giảm"), range: l("Range", "Đi ngang"), uncertain: l("Uncertain", "Chưa rõ") };
  const evidence = plan.evidence?.timeframes[forecast.timeframe]?.price_action;
  return <section aria-label={l("AI conditional trend outlook", "Dự báo xu hướng có điều kiện của AI")} className="rounded-lg border bg-muted/20 p-3 text-sm">
    <h3 className="font-semibold">{l("AI outlook", "Xu hướng AI dự kiến")}: {names[forecast.direction]} · {forexFrameLabel(forecast.timeframe)} · {forecast.horizon_bars} {l("next candles", "nến tiếp theo")}</h3>
    <p className="mt-2">{forecast.rationale}</p>
    <p className="mt-2 text-xs"><strong>{l("Invalidation", "Điều kiện vô hiệu")}: </strong>{forecast.invalidation}</p>
    {evidence?.status === "ok" && <p className="mt-2 text-xs text-muted-foreground">{l("Code-derived confirmation levels", "Mốc xác nhận tính từ dữ liệu")}: {l("closed candle above", "nến đóng trên")} {evidence.bullish_close_above ?? "—"} / {l("below", "dưới")} {evidence.bearish_close_below ?? "—"}.</p>}
    {evidence?.as_of && <p className="mt-2 text-xs text-muted-foreground">{l("Last closed input candle (bar open time, UTC)", "Nến đóng cuối trong dữ liệu (giờ mở nến, UTC)")}: {evidence.as_of.replace("T", " ")}. {l("The six-bar horizon starts after this candle; it does not move with the live chart.", "Horizon sáu nến tính sau nến này, không tự dịch theo chart đang cập nhật.")}</p>}
    <p className="mt-2 text-xs text-muted-foreground">{l("Snapshot", "Snapshot")}: {plan.created_at.replace("T", " ")}. {l("A direction outlook is separate from an entry recommendation; WAIT remains valid. No calibrated win probability is available.", "Nhận định hướng giá tách biệt với khuyến nghị vào lệnh; CHỜ vẫn có hiệu lực. Chưa có xác suất thắng được hiệu chỉnh bằng kiểm định.")}</p>
  </section>;
}
