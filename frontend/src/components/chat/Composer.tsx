import {
  forwardRef,
  memo,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type DragEvent,
  type FormEvent,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import {
  Download,
  Landmark,
  Loader2,
  Paperclip,
  Plus,
  Send,
  Square,
  Target,
  Users,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { UploadedAttachment } from "@/lib/attachments";
import { buildChatPrompt, MAX_GOAL_CHARS, MAX_MESSAGE_CHARS, promptExceedsLimit } from "@/lib/chatPrompt";
import type { AgentActivity } from "@/stores/agent";
import {
  LiveRuntimeControl,
  LiveRuntimeStatus,
} from "@/components/chat/LiveRuntimePanel";

const CONNECTOR_CHECK_PROMPT =
  "List my trading connector profiles, show which one is selected, then check that selected connector. If it is not ready, tell me exactly what setup step is missing. Do not place or modify orders.";
const CONNECTOR_PORTFOLIO_PROMPT =
  "Use the selected trading connector profile to summarize my account, positions, concentration, cash, and portfolio risk. Do not place or modify orders.";

const ACCEPTED_FILE_TYPES =
  ".pdf,.docx,.xlsx,.xls,.pptx,.csv,.tsv,.txt,.md,.log,.json,.toml,.html,.xml,.rst,.png,.jpg,.jpeg,.gif,.bmp,.webp,.tiff";
const MAX_ATTACHMENT_COUNT = 5;
const MAX_FILE_SIZE = 50 * 1024 * 1024;
const BLOCKED_EXTENSIONS = [
  ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".app", ".dmg",
  ".so", ".dll", ".dylib", ".py", ".pyw", ".sh", ".bash", ".zsh",
  ".fish", ".ps1", ".yaml", ".yml", ".j2", ".jinja", ".jinja2",
  ".template", ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2",
  ".xz",
];
const BLOCKED_FILENAMES = new Set(["dockerfile", "containerfile"]);

export type ComposerAttachment = UploadedAttachment;

export interface ComposerHandle {
  fill(prompt: string): void;
  focus(): void;
  submit(prompt: string): void;
}

interface Props {
  streaming: boolean;
  activityVerb?: AgentActivity["verb"];
  hasCompletedTurn: boolean;
  showExport: boolean;
  canExport: boolean;
  goalComposerActive: boolean;
  swarmPreset: { name: string; title: string } | null;
  panels?: ReactNode;
  onSubmit: (prompt: string, attachments: ComposerAttachment[]) => void;
  onCancel: () => void;
  onExport: () => void;
  onStartGoal: () => void;
  onCancelGoal: () => void;
  onStartSwarm: () => void;
  onCancelSwarm: () => void;
}

export const Composer = memo(forwardRef<ComposerHandle, Props>(function Composer({
  streaming,
  activityVerb,
  hasCompletedTurn,
  showExport,
  canExport,
  goalComposerActive,
  swarmPreset,
  panels,
  onSubmit,
  onCancel,
  onExport,
  onStartGoal,
  onCancelGoal,
  onStartSwarm,
  onCancelSwarm,
}, ref) {
  const { t } = useTranslation();
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const isComposingRef = useRef(false);
  const lastCompositionEndRef = useRef(0);
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [draggingFiles, setDraggingFiles] = useState(false);
  const dragDepthRef = useRef(0);
  const [showUploadMenu, setShowUploadMenu] = useState(false);
  const uploadMenuRef = useRef<HTMLDivElement>(null);
  const uploadMenuTriggerRef = useRef<HTMLButtonElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const focus = useCallback(() => {
    inputRef.current?.focus({ preventScroll: true });
  }, []);

  const submitPrompt = useCallback((prompt: string) => {
    if ((!prompt.trim() && attachments.length === 0) || streaming || uploading) return;
    const submitted = prompt.trim();
    const limit = goalComposerActive ? MAX_GOAL_CHARS : MAX_MESSAGE_CHARS;
    const requestText = goalComposerActive ? submitted : buildChatPrompt(submitted, attachments, Boolean(swarmPreset));
    if (promptExceedsLimit(requestText, limit)) {
      toast.error(t('agent.messageTooLong', { limit: limit.toLocaleString() }));
      return;
    }
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";
    const submittedAttachments = [...attachments];
    if (!goalComposerActive) setAttachments([]);
    onSubmit(submitted, submittedAttachments);
    inputRef.current?.focus();
  }, [attachments, goalComposerActive, onSubmit, streaming, swarmPreset, t, uploading]);

  useImperativeHandle(ref, () => ({
    fill(prompt: string) {
      setInput(prompt);
      requestAnimationFrame(() => {
        const composer = inputRef.current;
        if (!composer) return;
        composer.focus({ preventScroll: true });
        composer.style.height = "auto";
        composer.style.height = `${composer.scrollHeight}px`;
      });
    },
    focus,
    submit: submitPrompt,
  }), [focus, submitPrompt]);

  const handleSubmit = useCallback((event: FormEvent) => {
    event.preventDefault();
    submitPrompt(input);
  }, [input, submitPrompt]);

  const uploadFiles = useCallback(async (files: File[]) => {
    if (files.length === 0 || streaming || uploading) return;
    const remainingSlots = MAX_ATTACHMENT_COUNT - attachments.length;
    if (remainingSlots <= 0) {
      toast.error(t("agent.attachmentLimit", { count: MAX_ATTACHMENT_COUNT }));
      return;
    }
    const validFiles = files.filter((file) => {
      const lowered = file.name.toLowerCase();
      if (
        BLOCKED_FILENAMES.has(lowered)
        || BLOCKED_EXTENSIONS.some((extension) => lowered.endsWith(extension))
      ) {
        toast.error(t("agent.executablesNotAllowed"));
        return false;
      }
      if (file.size > MAX_FILE_SIZE) {
        toast.error(t("agent.fileSizeExceeds"));
        return false;
      }
      return true;
    });
    if (validFiles.length > remainingSlots) {
      toast.error(t("agent.attachmentLimit", { count: MAX_ATTACHMENT_COUNT }));
    }
    const accepted = validFiles.slice(0, remainingSlots);
    if (accepted.length === 0) return;

    setUploading(true);
    setShowUploadMenu(false);
    try {
      for (const file of accepted) {
        try {
          const result = await api.uploadFile(file);
          setAttachments((current) => [
            ...current,
            { filename: result.filename, filePath: result.file_path },
          ]);
          toast.success(t("agent.uploaded", { filename: result.filename }));
        } catch (error) {
          toast.error(t("agent.uploadFailed", {
            error: error instanceof Error ? error.message : "Unknown error",
          }));
        }
      }
    } finally {
      setUploading(false);
    }
  }, [attachments.length, streaming, t, uploading]);

  const handleFileSelect = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    void uploadFiles(files);
  }, [uploadFiles]);

  const handlePaste = useCallback((event: ClipboardEvent<HTMLFormElement>) => {
    const files = Array.from(event.clipboardData.files ?? []);
    if (files.length === 0) return;
    event.preventDefault();
    void uploadFiles(files);
  }, [uploadFiles]);

  const handleDragEnter = useCallback((event: DragEvent<HTMLFormElement>) => {
    if (streaming || uploading) return;
    if (!Array.from(event.dataTransfer.types ?? []).includes("Files")) return;
    event.preventDefault();
    dragDepthRef.current += 1;
    setDraggingFiles(true);
  }, [streaming, uploading]);

  const handleDragLeave = useCallback((event: DragEvent<HTMLFormElement>) => {
    event.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setDraggingFiles(false);
  }, []);

  const handleDrop = useCallback((event: DragEvent<HTMLFormElement>) => {
    event.preventDefault();
    dragDepthRef.current = 0;
    setDraggingFiles(false);
    void uploadFiles(Array.from(event.dataTransfer.files ?? []));
  }, [uploadFiles]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (uploadMenuRef.current && !uploadMenuRef.current.contains(event.target as Node)) {
        setShowUploadMenu(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setShowUploadMenu(false);
      uploadMenuTriggerRef.current?.focus();
    };
    if (showUploadMenu) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleEscape);
      return () => {
        document.removeEventListener("mousedown", handleClickOutside);
        document.removeEventListener("keydown", handleEscape);
      };
    }
  }, [showUploadMenu]);

  return (
    <form
      onSubmit={handleSubmit}
      onPaste={handlePaste}
      onDragEnter={handleDragEnter}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className="relative space-y-2"
    >
      {draggingFiles && (
        <div role="status" className="pointer-events-none absolute inset-0 z-50 flex items-center justify-center rounded-2xl border-2 border-dashed border-primary bg-background/90 text-sm font-medium text-primary">
          {t("agent.dropFiles")}
        </div>
      )}
      {swarmPreset && (
        <div className="flex items-center gap-1.5 px-1 animate-in fade-in">
          <span className="inline-flex items-center gap-2 px-3 py-1 rounded-xl bg-cyan-500/10 border border-cyan-500/25 text-cyan-400 text-xs font-semibold shadow-xs backdrop-blur-md">
            <Users className="h-3.5 w-3.5 text-cyan-400" />
            <span>Chuyên gia Swarm: {swarmPreset.title}</span>
            <button
              type="button"
              onClick={onCancelSwarm}
              className="rounded-md p-0.5 hover:bg-destructive/20 hover:text-destructive text-muted-foreground transition-colors"
              title="Hủy preset"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </span>
        </div>
      )}
      {goalComposerActive && (
        <div className="flex items-center gap-1.5 px-1 animate-in fade-in">
          <span className="inline-flex items-center gap-2 px-3 py-1 rounded-xl bg-orange-500/10 border border-orange-500/25 text-orange-400 text-xs font-semibold shadow-xs backdrop-blur-md">
            <Target className="h-3.5 w-3.5 text-orange-400" />
            <span>{t("agent.newResearchGoal")}</span>
            <button
              type="button"
              onClick={onCancelGoal}
              className="rounded-md p-0.5 hover:bg-destructive/20 hover:text-destructive text-muted-foreground transition-colors"
              title="Hủy mục tiêu"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </span>
        </div>
      )}
      {panels}
      <LiveRuntimeStatus />
      {attachments.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 px-1">
          {attachments.map((attachment, index) => {
            const ext = attachment.filename.split('.').pop()?.toUpperCase() || "FILE";
            return (
              <span
                key={attachment.filePath}
                className="group inline-flex max-w-full items-center gap-2 px-3 py-1.5 rounded-xl border border-primary/25 bg-[#0B1524]/80 text-foreground text-xs font-medium shadow-sm backdrop-blur-md transition-all hover:border-primary/40"
              >
                <span className="px-1.5 py-0.5 rounded bg-primary/20 text-primary text-[9px] font-mono font-bold tracking-wider">
                  {ext}
                </span>
                <span className="truncate max-w-[220px] text-foreground/90 font-medium">{attachment.filename}</span>
                <button
                  type="button"
                  aria-label={t("agent.removeAttachment", { filename: attachment.filename })}
                  onClick={() => setAttachments((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                  className="rounded-md p-0.5 hover:bg-destructive/20 hover:text-destructive text-muted-foreground/60 transition-colors"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </span>
            );
          })}
        </div>
      )}
      {uploading && (
        <div className="flex items-center gap-2 px-2 text-xs text-primary animate-pulse">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          <span>{t("agent.uploading")}</span>
        </div>
      )}
      <LiveRuntimeControl />

      {/* Main Composer Box with Dual-layer Glow & Glassmorphism */}
      <div className="relative group rounded-2xl transition-all duration-300">
        {/* Ambient glow backdrop on focus / streaming */}
        <div
          className={`absolute -inset-[1px] rounded-2xl transition-all duration-500 pointer-events-none ${
            streaming
              ? "bg-gradient-to-r from-rose-500/30 via-red-500/20 to-orange-500/30 blur-sm opacity-90 animate-pulse"
              : "bg-gradient-to-r from-primary/30 via-[#13C6B0]/25 to-primary/30 opacity-40 blur-[2px] group-focus-within:opacity-100 group-focus-within:blur-md"
          }`}
          aria-hidden="true"
        />

        {/* Inner Interactive Card */}
        <div
          className={`relative flex items-end gap-2.5 rounded-2xl p-2.5 backdrop-blur-2xl transition-all duration-300 ${
            streaming
              ? "bg-[#0A101D]/95 border border-rose-500/35 shadow-[0_8px_32px_-8px_rgba(244,63,94,0.3)]"
              : "bg-[#0B1422]/90 dark:bg-[#070D18]/95 border border-white/[0.12] dark:border-white/[0.08] group-focus-within:border-primary/50 shadow-[0_8px_32px_-8px_rgba(0,0,0,0.5),inset_0_1px_1px_0_rgba(255,255,255,0.08)] group-focus-within:shadow-[0_12px_40px_-10px_rgba(234,88,12,0.22),inset_0_1px_1px_0_rgba(255,255,255,0.12)]"
          }`}
        >
          {/* Options / Upload Menu Button */}
          <div className="relative shrink-0" ref={uploadMenuRef}>
            <button
              ref={uploadMenuTriggerRef}
              type="button"
              onClick={() => setShowUploadMenu((previous) => !previous)}
              disabled={streaming || uploading}
              aria-haspopup="menu"
              aria-expanded={showUploadMenu}
              aria-controls="agent-more-options-menu"
              className={`w-9 h-9 rounded-xl flex items-center justify-center transition-all duration-200 disabled:opacity-40 shrink-0 ${
                showUploadMenu
                  ? "bg-primary text-white shadow-[0_0_14px_rgba(234,88,12,0.5)] rotate-45"
                  : "bg-white/[0.04] hover:bg-white/[0.09] text-muted-foreground hover:text-foreground border border-white/[0.08] hover:border-white/20 active:scale-95 shadow-sm"
              }`}
              title={t("agent.moreOptions")}
            >
              <Plus className="h-4 w-4 transition-transform duration-200" />
            </button>

            {showUploadMenu && (
              <div
                id="agent-more-options-menu"
                role="menu"
                className="absolute bottom-full left-0 mb-3 w-64 rounded-2xl border border-white/10 bg-[#0E1724]/95 backdrop-blur-xl shadow-[0_16px_50px_-10px_rgba(0,0,0,0.7),inset_0_1px_1px_0_rgba(255,255,255,0.08)] p-2 z-50 animate-in fade-in slide-in-from-bottom-2 duration-200 space-y-1 text-xs"
              >
                <div className="px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                  {t("agent.moreOptions")}
                </div>

                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    fileInputRef.current?.click();
                    setShowUploadMenu(false);
                  }}
                  className="w-full px-3 py-2 text-left rounded-xl hover:bg-white/[0.08] transition-colors flex items-center gap-3 font-medium text-foreground group"
                >
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/15 text-primary group-hover:scale-105 transition-transform">
                    <Paperclip className="h-3.5 w-3.5" />
                  </span>
                  <div>
                    <div className="font-semibold text-xs">{t("agent.uploadFile")}</div>
                    <div className="text-[10px] text-muted-foreground/70">Tài liệu, ảnh, bảng tính BCTC</div>
                  </div>
                </button>

                <div className="border-t border-white/[0.06] my-1" />

                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setShowUploadMenu(false);
                    onStartGoal();
                    inputRef.current?.focus();
                  }}
                  className="w-full px-3 py-2 text-left rounded-xl hover:bg-white/[0.08] transition-colors flex items-center gap-3 font-medium text-foreground group"
                >
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-orange-500/15 text-orange-400 group-hover:scale-105 transition-transform">
                    <Target className="h-3.5 w-3.5" />
                  </span>
                  <div>
                    <div className="font-semibold text-xs">{t("agent.researchGoal")}</div>
                    <div className="text-[10px] text-muted-foreground/70">Mục tiêu nghiên cứu đa bước</div>
                  </div>
                </button>

                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setShowUploadMenu(false);
                    onStartSwarm();
                    inputRef.current?.focus();
                  }}
                  className="w-full px-3 py-2 text-left rounded-xl hover:bg-white/[0.08] transition-colors flex items-center gap-3 font-medium text-foreground group"
                >
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-cyan-500/15 text-cyan-400 group-hover:scale-105 transition-transform">
                    <Users className="h-3.5 w-3.5" />
                  </span>
                  <div>
                    <div className="font-semibold text-xs">{t("agent.agentSwarm")}</div>
                    <div className="text-[10px] text-muted-foreground/70">Phối hợp đội ngũ chuyên gia AI</div>
                  </div>
                </button>

                <div className="border-t border-white/[0.06] my-1" />

                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setShowUploadMenu(false);
                    submitPrompt(CONNECTOR_CHECK_PROMPT);
                  }}
                  className="w-full px-3 py-2 text-left rounded-xl hover:bg-white/[0.08] transition-colors flex items-center gap-3 font-medium text-foreground group"
                >
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400 group-hover:scale-105 transition-transform">
                    <Landmark className="h-3.5 w-3.5" />
                  </span>
                  <div>
                    <div className="font-semibold text-xs">{t("agent.checkConnector")}</div>
                    <div className="text-[10px] text-muted-foreground/70">Kiểm tra kết nối broker & sàn</div>
                  </div>
                </button>

                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setShowUploadMenu(false);
                    submitPrompt(CONNECTOR_PORTFOLIO_PROMPT);
                  }}
                  className="w-full px-3 py-2 text-left rounded-xl hover:bg-white/[0.08] transition-colors flex items-center gap-3 font-medium text-foreground group"
                >
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400 group-hover:scale-105 transition-transform">
                    <Landmark className="h-3.5 w-3.5" />
                  </span>
                  <div>
                    <div className="font-semibold text-xs">{t("agent.analyzePortfolio")}</div>
                    <div className="text-[10px] text-muted-foreground/70">Đánh giá rủi ro danh mục</div>
                  </div>
                </button>
              </div>
            )}
          </div>

          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_FILE_TYPES}
            onChange={handleFileSelect}
            className="hidden"
          />

          {/* Prompt Textarea */}
          <textarea
            ref={inputRef}
            dir="auto"
            value={input}
            rows={1}
            onChange={(e) => setInput(e.target.value)}
            onCompositionStart={() => {
              isComposingRef.current = true;
            }}
            onCompositionEnd={() => {
              isComposingRef.current = false;
              lastCompositionEndRef.current = Date.now();
            }}
            onInput={(e) => {
              const el = e.target as HTMLTextAreaElement;
              el.style.height = "auto";
              el.style.height = Math.min(el.scrollHeight, 180) + "px";
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                const nativeEvent = e.nativeEvent as KeyboardEvent & { isComposing?: boolean };
                const justFinishedComposing = Date.now() - lastCompositionEndRef.current < 80;
                if (isComposingRef.current || nativeEvent.isComposing || nativeEvent.keyCode === 229) {
                  return;
                }
                if (justFinishedComposing) {
                  e.preventDefault();
                  return;
                }
                e.preventDefault();
                submitPrompt(input);
              }
            }}
            placeholder={
              streaming
                ? t(`agent.activity.verbs.${activityVerb ?? "working"}` as never)
                : goalComposerActive
                ? t("agent.describeGoal")
                : hasCompletedTurn
                ? t("agent.followUpPlaceholder" as never)
                : t("agent.placeholder")
            }
            aria-label={t("agent.messageInputLabel")}
            aria-readonly={streaming}
            className={[
              "min-h-[44px] flex-1 resize-none overflow-y-auto bg-transparent px-3 py-2.5 text-sm leading-relaxed outline-none max-h-44",
              "placeholder:text-muted-foreground/45 focus:outline-none selection:bg-primary/20",
              streaming ? "cursor-not-allowed text-muted-foreground/70" : "text-foreground",
            ].join(" ")}
            readOnly={streaming}
          />

          {/* Export Button */}
          {showExport && (
            <button
              type="button"
              onClick={onExport}
              disabled={!canExport}
              className="h-9 w-9 rounded-xl border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.08] flex items-center justify-center text-muted-foreground hover:text-foreground active:scale-95 transition-all disabled:opacity-20 disabled:pointer-events-none shrink-0"
              title={t("agent.exportChat")}
            >
              <Download className="h-4 w-4" />
            </button>
          )}

          {/* Send / Stop Action Button */}
          {streaming ? (
            <button
              type="button"
              onClick={onCancel}
              className="group relative h-9 w-9 rounded-xl bg-gradient-to-r from-rose-500/20 via-red-500/25 to-rose-500/20 border border-rose-500/40 text-rose-300 shadow-[0_0_15px_rgba(244,63,94,0.25)] hover:bg-rose-500/30 hover:border-rose-500/60 hover:shadow-[0_0_20px_rgba(244,63,94,0.45)] active:scale-95 transition-all flex items-center justify-center shrink-0"
              title={t("agent.stopGeneration")}
              aria-label={t("agent.stopGeneration")}
            >
              <Square className="h-3.5 w-3.5 fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={uploading || (goalComposerActive ? !input.trim() : (!input.trim() && attachments.length === 0))}
              className="h-9 px-3.5 sm:px-4 rounded-xl bg-gradient-to-r from-amber-500 via-orange-500 to-amber-600 hover:from-amber-400 hover:via-orange-500 hover:to-amber-500 text-white text-xs font-semibold shadow-[0_2px_14px_rgba(234,88,12,0.35)] hover:shadow-[0_4px_22px_rgba(234,88,12,0.55)] active:scale-95 transition-all duration-200 disabled:opacity-25 disabled:pointer-events-none disabled:shadow-none flex items-center justify-center gap-1.5 shrink-0"
              title={t("agent.send")}
              aria-label={t("agent.send")}
            >
              <Send className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Gửi</span>
            </button>
          )}
        </div>
      </div>
    </form>
  );
}));
