import { authHeaders } from "./apiAuth";
import type { PriceActionEvidence } from "./forexChart";

export interface ForexLimits {
  max_order_notional_usd: string; max_total_exposure_usd: string; max_stop_risk_usd: string;
  max_equity_drawdown_usd: string; max_quantity: string; max_spread_points: string;
  max_quote_age_seconds: number; max_orders_per_day: number; max_leverage: string; max_deviation_points: number;
}
export interface ForexConfig {
  id: string; label: string; connector: "mt5" | "exness" | "oanda"; account_ref: string;
  environment: "demo" | "live"; execution_enabled: boolean; symbols: string[];
  terminal_path: string; server: string; gateway_url: string; allowed_hosts: string[]; limits: ForexLimits;
  session_mode?: "credentials" | "existing_terminal";
}
export interface ForexConnection extends ForexConfig {
  mandate_key: string; credential_ref: string; halted: boolean; identity_locked?: boolean;
  global_halted?: boolean; broker_halted?: boolean; connection_halted?: boolean;
}
export interface ForexOrder {
  action?: "open" | "close"; position_ticket?: string;
  symbol: string; side: "buy" | "sell"; quantity: string; stop_loss?: string | null; take_profit?: string | null;
  request_key: string; expires_at: string; strategy_revision: string;
}
export interface ForexIntent {
  id: string; connection_id: string; state: string; created_at: string;
  payload: ForexOrder; result: Record<string, unknown>;
}
export interface ForexRunner { running: boolean; status: string; checked_at?: string; error?: string; intent_id?: string; mode?: "ai" | "sma" }
export interface ForexAnalysis {
  status: string; code?: string; error?: string; last_bar?: string; created_at?: string; expires_at?: string;
  model?: { provider: string; model: string }; execution_status?: string;
  decision?: { action: "buy" | "sell" | "hold" | "close"; confidence: number; rationale: string; stop_loss: string | null; take_profit: string | null };
  evidence?: ForexResearchEvidence;
}
export interface ForexResearchEvidence {
  medium_term_price_context_ready: boolean;
  timeframes: Record<string, { status: string; candle_count?: number; first_bar?: string; last_bar?: string; history_sufficient: boolean; indicators?: Record<string, number | null>; price_action?: PriceActionEvidence }>;
  macro: Record<string, { status: string; as_of?: string; source?: string; source_url?: string; unit?: string; latest?: { value?: number; tonnes?: number } }>;
}
export interface ForexAccount {
  account_ref: string; environment: string; equity: string; currency: string; trade_allowed: boolean;
  terminal_trade_allowed?: boolean; external_api_disabled?: boolean; hedging?: boolean;
  positions: { ticket: number; symbol: string; type: number; volume: number; profit: number; managed?: boolean }[];
}
export interface ForexProposal {
  proposal_id: string; account_ref: string;
  profiles: { ordinal: number; max_order_usd: number; max_total_exposure_usd: number; daily_trade_cap: number; leverage: number | string; instruments: string[] }[];
}
export async function forexRequest<T>(path: string, body?: unknown, method?: string, timeoutMs = 60000): Promise<T> {
  const response = await fetch(path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: { ...authHeaders(), ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(timeoutMs),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const validation = Array.isArray(detail) ? detail.map((row: { loc?: string[]; msg?: string }) => `${row.loc?.join(".") || "input"}: ${row.msg || "Invalid value"}`).join("; ") : undefined;
    throw new Error(typeof detail === "string" ? detail : detail?.error || validation || `Forex request failed (${response.status})`);
  }
  return data as T;
}
export const forexPath = (id: string) => `/api/forex/connections/${encodeURIComponent(id)}`;
export const defaultForexLimits: ForexLimits = {
  max_order_notional_usd: "1000", max_total_exposure_usd: "3000", max_stop_risk_usd: "10",
  max_equity_drawdown_usd: "50", max_quantity: "0.01", max_spread_points: "30",
  max_quote_age_seconds: 10, max_orders_per_day: 5, max_leverage: "2", max_deviation_points: 20,
};
export function editableForex(c?: ForexConnection): ForexConfig {
  return c ? { id: c.id, label: c.label, connector: c.connector, account_ref: c.account_ref,
    environment: c.environment, execution_enabled: c.execution_enabled, symbols: [...c.symbols],
    terminal_path: c.terminal_path, session_mode: c.session_mode || "credentials", server: c.server, gateway_url: c.gateway_url, allowed_hosts: [...c.allowed_hosts], limits: { ...c.limits } }
    : { id: "forex-demo", label: "Forex", connector: "mt5", account_ref: "", environment: "demo", execution_enabled: false,
      symbols: [], terminal_path: "", server: "", gateway_url: "", allowed_hosts: [], limits: { ...defaultForexLimits } };
}
