import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Brain, ChevronDown, RefreshCw } from "lucide-react";
import { authHeaders } from "@/lib/apiAuth";

interface Selection { eligible_messages?: number; recent_messages?: number; retrieved_messages?: number; omitted_messages?: number; truncated_recent_messages?: number; history_chars?: number; history_char_budget?: number }
export interface ContextSnapshot {
  version: 1; source: string; run_id: string;
  session_id?: string; attempt_id?: string;
  initial_selection?: Selection;
  initial_components?: { prompt_profile?: string; system_chars?: number; recalled_memories?: Array<{ title: string; type: string }> };
  current_prompt?: { estimated_next_request_tokens?: number; last_reported_input_tokens?: number | null; model_window?: number; window_source?: string; window_confidence?: string; model?: string; provider?: string; phase?: "pre_request" | "post_response" | "post_compaction" | "final"; observed_at?: string; prompt_cost_cap?: number; compact_at?: number };
  compaction?: { state: "idle" | "running" | "completed" | "failed" | "skipped"; automatic?: boolean; count?: number; updated_at?: string };
}
export interface ContextView {
  version: 1; session_id: string; model_calls: 0; stored_messages: number; preview: Selection;
  last_run: ContextSnapshot | null;
  current_context?: ContextSnapshot | null;
  last_run_usage?: { totals?: { input_tokens?: number; output_tokens?: number; calls?: number; cache_read_tokens?: number } } | null;
  last_run_council_usage_tracked?: boolean | null;
  model_context?: { model?: string; provider?: string; window?: number; source?: string; confidence?: string; prompt_cost_cap?: number; compact_at?: number; automatic_compaction?: boolean } | null;
  memory: { available_entries: number | null; error: string | null; entries: Array<{ id: string; title: string; type: string }>; recall_preview: Array<{ id: string; title: string; type: string; excerpt: string }>; automatic_fact_extraction: false };
}

export function ContextMemoryPanel({ sessionId, live, embedded = false }: { sessionId: string | null; live?: ContextSnapshot; embedded?: boolean }) {
  const { i18n } = useTranslation();
  const vi = i18n.language.startsWith("vi");
  const l = (en: string, vn: string) => vi ? vn : en;
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ContextView>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [memoryTitle, setMemoryTitle] = useState("");
  const [memoryContent, setMemoryContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveNotice, setSaveNotice] = useState("");
  const saveMemory = async () => {
    if (!sessionId) return;
    setSaving(true); setSaveNotice("");
    try {
      const r = await fetch(`/sessions/${encodeURIComponent(sessionId)}/memory`, { method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ title: memoryTitle.trim(), content: memoryContent.trim(), memory_type: "user" }) });
      if (!r.ok) throw new Error(l("Cannot save memory", "Không lưu được ghi nhớ"));
      const result = await r.json();
      setSaveNotice(result.status === "saved" ? l("Memory saved for future turns. No model call was made.", "Đã lưu cho các lượt sau, không gọi model.") : l("No new memory was saved; the entry may already exist or storage is busy.", "Chưa lưu mục mới; có thể đã trùng hoặc kho nhớ đang bận."));
      if (result.status === "saved") { setMemoryTitle(""); setMemoryContent(""); setRevision(v => v + 1); }
    } catch (e) { setSaveNotice(e instanceof Error ? e.message : String(e)); }
    finally { setSaving(false); }
  };
  useEffect(() => { setData(undefined); setError(""); }, [sessionId]);
  useEffect(() => {
    if (!open || !sessionId) return;
    let active = true;
    const controller = new AbortController();
    setLoading(true); setError("");
    void fetch(`/sessions/${encodeURIComponent(sessionId)}/context`, { headers: authHeaders(), signal: controller.signal })
      .then(async r => { if (!r.ok) throw new Error(l("Cannot read context diagnostics", "Không đọc được thông tin context")); return r.json(); })
      .then(value => {
        if (value?.version !== 1 || value.session_id !== sessionId || !value.memory || !Array.isArray(value.memory.entries) || !Array.isArray(value.memory.recall_preview)) throw new Error(l("Invalid context response", "Phản hồi context không hợp lệ"));
        if (active) setData(value);
      })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [open, sessionId, revision, vi, live?.run_id]);
  const snapshot = live || data?.last_run;
  const selection = snapshot?.initial_selection || data?.preview;
  const prompt = snapshot?.current_prompt;
  const usage = data?.last_run_usage?.totals;
  const n = (value?: number | null) => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString(vi ? "vi-VN" : "en-US") : "—";
  return <details open={open} onToggle={e => setOpen(e.currentTarget.open)} className={`shrink-0 ${embedded ? "border-t" : "border-b bg-muted/10"} text-xs`}>
    <summary className={`flex cursor-pointer flex-wrap items-center gap-2 ${embedded ? "py-2" : "px-4 py-2"} font-medium`}><Brain size={14} aria-hidden="true" />{embedded ? l("History & long-term memory", "Lịch sử & bộ nhớ dài hạn") : l("Context & memory", "Context & bộ nhớ")}
      {live?.current_prompt?.last_reported_input_tokens != null && <span className="font-normal text-muted-foreground">· {n(live.current_prompt.last_reported_input_tokens)} {l("input tokens in last main request", "token input ở request chính gần nhất")}</span>}
      <ChevronDown size={13} className={open ? "rotate-180" : ""} aria-hidden="true" />
    </summary>
    {open && <div className={`space-y-3 pb-3 ${embedded ? "" : "max-h-[50vh] overflow-auto px-4"}`}>
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-muted-foreground">{l("Inspecting this panel makes no model calls. Stored history, recalled memory and billed tokens are different quantities.", "Mở bảng này không gọi model. Lịch sử đã lưu, bộ nhớ được truy xuất và token đã dùng là các số khác nhau.")}</p><button className="inline-flex items-center gap-1 rounded border px-2 py-1" disabled={loading || !sessionId} onClick={() => setRevision(v => v + 1)}><RefreshCw size={12} />{l("Refresh", "Làm mới")}</button></div>
      {!sessionId && <p>{l("Select a conversation to inspect its context.", "Chọn một phiên chat để xem context.")}</p>}
      {loading && <p role="status">{l("Reading saved state…", "Đang đọc dữ liệu đã lưu…")}</p>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {data && <>
        <div className={embedded ? "space-y-3" : "grid gap-3 sm:grid-cols-2"}>
          <section className="rounded-lg border p-3"><h3 className="font-semibold">{l("Session context", "Bộ nhớ phiên chat")}</h3>
            <p className="mt-1">{l("Saved messages", "Tin nhắn đã lưu")}: {n(data.stored_messages)}</p>
            <p>{snapshot ? l("Initial selection in the recorded run", "Lịch sử nạp ở đầu lượt đã ghi nhận") : l("Preview for the next turn", "Dự kiến lịch sử cho lượt tới")}: {n(selection?.recent_messages)} {l("recent", "gần nhất")} + {n(selection?.retrieved_messages)} {l("recalled older messages", "tin cũ được truy xuất")}</p>
            <p>{l("History characters / budget", "Ký tự lịch sử / giới hạn")}: {n(selection?.history_chars)} / {n(selection?.history_char_budget)}</p>
            {!!selection?.truncated_recent_messages && <p>{n(selection.truncated_recent_messages)} {l("recent messages were shortened; full messages remain stored.", "tin gần nhất đã rút gọn; bản đầy đủ vẫn được lưu.")}</p>}
            <p className="mt-1 text-muted-foreground">{n(selection?.omitted_messages)} {snapshot?.source === "historical_forex_report" ? l("other messages remain stored. This turn selected the saved structured WAIT report directly.", "tin khác vẫn được lưu. Lượt này chọn trực tiếp báo cáo CHỜ có cấu trúc đã lưu.") : l("messages remain stored outside the current selection. Older excerpts are retrieved by keywords; this is not a semantic or lossless summary.", "tin vẫn được lưu nhưng nằm ngoài phần đang nạp. Tin cũ được chọn theo từ khóa; đây chưa phải tóm tắt ngữ nghĩa hoặc bộ nhớ không mất thông tin.")}</p>
          </section>
          <section className="rounded-lg border p-3"><h3 className="font-semibold">{l("Persistent memory", "Bộ nhớ dài hạn")}</h3>
            <p className="mt-1">{l("Saved entries", "Mục đã lưu")}: {n(data.memory.available_entries)}</p>
            <p className="text-muted-foreground">{l("Shared across conversations in this local runtime.", "Dùng chung giữa các phiên trong runtime này.")}</p>
            {data.memory.error && <p className="text-destructive">{data.memory.error}</p>}
            <p>{l("Actually recalled at run start", "Đã truy xuất ở đầu lượt")}: {snapshot ? n(snapshot.initial_components?.recalled_memories?.length) : "—"}</p>
            {data.memory.available_entries === 0 && <p className="mt-1">{l("No durable memories have been saved yet.", "Chưa có ghi nhớ dài hạn nào được lưu.")}</p>}
            <p className="mt-1 text-muted-foreground">{l("The remember tool saves explicit preferences/context. There is no automatic fact extraction after every turn. Stored prices and analyses never replace fresh broker evidence.", "Tool remember có thể lưu sở thích/bối cảnh. Hiện không tự trích xuất ghi nhớ sau mỗi lượt. Giá và phân tích đã lưu không thay thế bằng chứng broker mới.")}</p>
            {data.memory.entries.length > 0 && <ul className="mt-2 space-y-1">{data.memory.entries.map(e => <li key={e.id}>{e.title} · {e.type}</li>)}</ul>}
            <details className="mt-2"><summary className="cursor-pointer font-medium">{l("Save a preference without a model call", "Lưu ghi nhớ trực tiếp, không gọi model")}</summary>
              <form className="mt-2 space-y-2" onSubmit={e => { e.preventDefault(); void saveMemory(); }}>
                <label className="block">{l("Memory title", "Tiêu đề ghi nhớ")}<input className="mt-1 w-full rounded border bg-background p-2" required maxLength={120} value={memoryTitle} onChange={e => setMemoryTitle(e.target.value)} /></label>
                <label className="block">{l("Preference or workflow", "Sở thích hoặc quy trình")}<textarea className="mt-1 w-full rounded border bg-background p-2" required maxLength={4000} rows={3} value={memoryContent} onChange={e => setMemoryContent(e.target.value)} /></label>
                <p className="text-muted-foreground">{l("Save stable preferences, not current market prices. Memories never grant trading permission.", "Lưu sở thích ổn định; giá hiện tại cần lấy mới. Ghi nhớ không cấp quyền giao dịch.")}</p>
                <button className="rounded border px-3 py-1.5" disabled={saving || !memoryTitle.trim() || !memoryContent.trim()}>{saving ? l("Saving…", "Đang lưu…") : l("Save memory", "Lưu ghi nhớ")}</button>
                {saveNotice && <p role="status">{saveNotice}</p>}
              </form>
            </details>
          </section>
        </div>
        {snapshot?.source === "historical_forex_report" ? <p className="rounded-lg border p-3">{l("This turn replayed a saved Forex report directly. No model requests, quote fetches or orders; model token usage is zero.", "Lượt này đọc trực tiếp báo cáo Forex đã lưu. Không gọi model, lấy giá mới hay gửi lệnh; token model bằng 0.")}</p> : prompt ? <section className="rounded-lg border p-3"><h3 className="font-semibold">{l("Main model request", "Request của model chính")}</h3>
          {snapshot?.initial_components?.prompt_profile && <p>{l("Prompt profile", "Phạm vi prompt")}: {snapshot.initial_components.prompt_profile}</p>}
          <p>{l("Provider-reported input in last request", "Input request gần nhất do provider báo")}: {n(prompt.last_reported_input_tokens)} · {l("Estimated prompt at snapshot", "Ước lượng prompt lúc ghi nhận")}: ~{n(prompt.estimated_next_request_tokens)}</p>
          <p>{l("Prompt cost ceiling", "Trần độ dài prompt")}: {n(prompt.prompt_cost_cap)} · {l("Compaction threshold", "Ngưỡng nén context")}: {n(prompt.compact_at)}</p>
          <p className="mt-1 text-muted-foreground">{l("Estimates use characters/4, anchored to reported usage when available. The prompt ceiling is not a cumulative spending budget. It excludes separate council requests.", "Ước lượng theo ký tự/4, hiệu chỉnh bằng usage khi có. Trần prompt không phải ngân sách tiêu thụ cộng dồn và không bao gồm request riêng của council.")}</p>
        </section> : <p className="text-muted-foreground">{l("This older run has no recorded context snapshot. The selection above is a preview, not proof of its past input.", "Lượt cũ chưa có bản ghi context. Phần lịch sử trên là dự kiến, không phải bằng chứng về đầu vào của lượt cũ.")}</p>}
        {usage && <p>{l("Last run's recorded tokens", "Token đã ghi nhận ở lượt gần nhất")}: input {n(usage.input_tokens)} · output {n(usage.output_tokens)} · {n(usage.calls)} {l("reported calls", "lời gọi có usage")} · cache {n(usage.cache_read_tokens)} ({l("already included in input; monetary cost unknown", "đã nằm trong input; chưa quy đổi chi phí tiền")}).</p>}
        {data.last_run_council_usage_tracked === false && <p className="text-amber-700 dark:text-amber-400">{l("This older token record does not include council calls. New runs account for them separately by role.", "Bản ghi token cũ chưa gồm các lời gọi council. Lượt chạy mới cộng riêng usage theo từng vai trò.")}</p>}
        {data.memory.recall_preview.length > 0 && <details><summary className="cursor-pointer">{l("Memory retrieval preview for the latest question", "Ghi nhớ có thể truy xuất theo câu hỏi gần nhất")}</summary>{data.memory.recall_preview.map(e => <p key={e.id} className="mt-2 whitespace-pre-wrap break-words"><strong>{e.title}</strong> · {e.excerpt}</p>)}</details>}
      </>}
    </div>}
  </details>;
}
