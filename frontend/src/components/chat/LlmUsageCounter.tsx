import { useTranslation } from "react-i18next";
import { abbreviateNum } from "@/lib/formatters";

interface LlmUsageCounterProps {
  input: number;
  output: number;
  calls?: number;
  cached?: number;
  cacheReportedCalls?: number;
  missingCalls?: number;
}

/**
 * Live token counter for the in-flight attempt, fed by `llm_usage` SSE
 * events. Renders nothing before the first usage delta arrives — a chat
 * stream that never measured a call shows no fabricated zero.
 */
export function LlmUsageCounter({ input, output, calls, cached, cacheReportedCalls, missingCalls }: LlmUsageCounterProps) {
  const { t, i18n } = useTranslation();
  const vi = i18n?.language.startsWith("vi");
  if (input === 0 && output === 0 && !missingCalls) return null;
  const unknownOnly = !!missingCalls && calls === missingCalls;
  return (
    <p className="px-3 text-xs text-muted-foreground" title={vi ? "Tổng token các lời gọi trong lượt này, không phải kích thước context. Cache đã nằm trong input; chưa quy đổi thành tiền." : "Cumulative tokens across this turn's calls, not context size. Cached tokens are included in input; this is not a monetary cost."}>
      {"\u2191"}{unknownOnly ? "—" : abbreviateNum(input)} {"\u2193"}{unknownOnly ? "—" : abbreviateNum(output)} {t("agent.tokenUsage.live")}
      {calls !== undefined && ` · ${calls} ${vi ? "lời gọi" : "calls"}`}
      {!!missingCalls && ` · ${missingCalls} ${vi ? "lời gọi chưa có usage" : "calls with unknown usage"}`}
      {!!cacheReportedCalls && ` · cache ${abbreviateNum(cached || 0)} (${vi ? "đã gồm trong input" : "included in input"}${cacheReportedCalls !== calls ? vi ? ", báo cáo một phần" : ", partial reporting" : ""})`}
    </p>
  );
}
