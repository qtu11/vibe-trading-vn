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
  ArrowUp,
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
import { cn } from "@/lib/utils";
import { MenuItem } from "@/components/ui/MenuItem";
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
  controls?: ReactNode;
  onSubmit: (prompt: string, attachments: ComposerAttachment[]) => void;
  onCancel: () => void;
  onExport: () => void;
  onStartGoal: () => void;
  onCancelGoal: () => void;
  onStartSwarm: () => void;
  onCancelSwarm: () => void;
}

/**
 * The prompt composer.
 *
 * The prompt is the subject of this surface, so the textarea is the largest
 * element and every auxiliary control (attachments, model, context, send)
 * is deliberately quiet: small, low-contrast until hovered or focused, and
 * laid out on a single toolbar row under the text.
 */
export const Composer = memo(forwardRef<ComposerHandle, Props>(function Composer({
  streaming,
  activityVerb,
  hasCompletedTurn,
  showExport,
  canExport,
  goalComposerActive,
  swarmPreset,
  panels,
  controls,
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
        <div
          role="status"
          className="vt-pop-in pointer-events-none absolute inset-0 z-50 flex items-center justify-center rounded-2xl border-2 border-dashed border-accent bg-surface-overlay/95 text-sm font-medium text-accent-ink"
        >
          {t("agent.dropFiles")}
        </div>
      )}
      {swarmPreset && (
        <div className="flex items-center gap-1.5 px-1 animate-in fade-in">
          <span className="inline-flex items-center gap-2 rounded-lg border border-info/25 bg-info/10 px-2.5 py-1 text-xs font-semibold text-info">
            <Users className="h-3.5 w-3.5" />
            <span>Chuyên gia Swarm: {swarmPreset.title}</span>
            <button
              type="button"
              onClick={onCancelSwarm}
              className="vt-focus-visible rounded p-0.5 text-ink-muted transition-colors hover:bg-danger/10 hover:text-danger"
              title="Hủy preset"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </span>
        </div>
      )}
      {goalComposerActive && (
        <div className="flex items-center gap-1.5 px-1 animate-in fade-in">
          <span className="inline-flex items-center gap-2 rounded-lg border border-warning/25 bg-warning/10 px-2.5 py-1 text-xs font-semibold text-warning">
            <Target className="h-3.5 w-3.5" />
            <span>{t("agent.newResearchGoal")}</span>
            <button
              type="button"
              onClick={onCancelGoal}
              className="vt-focus-visible rounded p-0.5 text-ink-muted transition-colors hover:bg-danger/10 hover:text-danger"
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
        <div className="flex flex-wrap items-center gap-1.5 px-1">
          {attachments.map((attachment, index) => {
            const ext = attachment.filename.split('.').pop()?.toUpperCase() || "FILE";
            return (
              <span
                key={attachment.filePath}
                className="group inline-flex max-w-full items-center gap-1.5 rounded-lg border border-hairline bg-surface-raised px-2 py-1 text-xs font-medium text-ink-secondary shadow-xs transition-colors hover:border-hairline-strong"
              >
                <span className="vt-num rounded bg-accent/10 px-1 py-0.5 font-mono text-[9px] font-bold tracking-wider text-accent-ink">
                  {ext}
                </span>
                <span className="truncate max-w-[220px] text-ink">{attachment.filename}</span>
                <button
                  type="button"
                  aria-label={t("agent.removeAttachment", { filename: attachment.filename })}
                  onClick={() => setAttachments((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                  className="vt-focus-visible rounded p-0.5 text-ink-faint transition-colors hover:bg-danger/10 hover:text-danger"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </span>
            );
          })}
        </div>
      )}
      {uploading && (
        <div className="flex items-center gap-2 px-2 text-xs text-accent-ink animate-pulse">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          <span>{t("agent.uploading")}</span>
        </div>
      )}
      <LiveRuntimeControl />

      <div
        data-composer-frame
        className={cn(
          "relative rounded-2xl border border-hairline bg-surface-raised px-3.5 py-2.5 sm:px-4 sm:py-3",
          "shadow-panel transition-[border-color,box-shadow] duration-[--dur-fast] ease-standard",
          "hover:border-hairline-strong focus-within:border-accent/50 focus-within:shadow-float",
          streaming && "opacity-90",
        )}
      >
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
            el.style.height = Math.min(el.scrollHeight, 160) + "px";
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
            "min-h-[42px] w-full resize-none overflow-y-auto bg-transparent px-1 py-1 text-[15px] leading-relaxed outline-none max-h-40",
            "placeholder:text-ink-faint selection:bg-accent/25",
            streaming ? "cursor-not-allowed text-ink-muted" : "text-ink",
          ].join(" ")}
          readOnly={streaming}
        />

        <div data-composer-toolbar className="flex min-w-0 items-center gap-2">
          {/* Options / Upload Menu Button */}
          <div className="relative shrink-0 flex items-center gap-2" ref={uploadMenuRef}>
            <button
              ref={uploadMenuTriggerRef}
              type="button"
              onClick={() => setShowUploadMenu((previous) => !previous)}
              disabled={streaming || uploading}
              aria-haspopup="menu"
              aria-expanded={showUploadMenu}
              aria-controls="agent-more-options-menu"
              className={cn(
                "vt-focus-visible flex h-7 w-7 items-center justify-center rounded-md transition-all duration-[--dur-fast] disabled:opacity-40 shrink-0",
                showUploadMenu
                  ? "bg-muted text-ink rotate-45"
                  : "text-ink-muted hover:bg-muted hover:text-ink active:scale-95",
              )}
              title={t("agent.moreOptions")}
            >
              <Plus className="h-4 w-4 transition-transform duration-[--dur-fast]" />
            </button>
            {showUploadMenu && (
              <div
                id="agent-more-options-menu"
                role="menu"
                className={cn(
                  "vt-pop-in absolute bottom-full left-0 mb-2 w-64 rounded-xl border border-hairline",
                  "bg-surface-overlay p-1.5 z-50 space-y-0.5 text-xs shadow-lg",
                )}
              >
                <div className="px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink-faint">
                  {t("agent.moreOptions")}
                </div>

                <MenuItem
                  icon={<Paperclip className="h-3.5 w-3.5" />}
                  title={t("agent.uploadFile")}
                  description="Tài liệu, ảnh, bảng tính BCTC"
                  onClick={() => {
                    fileInputRef.current?.click();
                    setShowUploadMenu(false);
                  }}
                />

                <div className="my-1 h-px bg-hairline-subtle" />

                {showExport && (
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!canExport}
                    onClick={() => { setShowUploadMenu(false); onExport(); }}
                    className="vt-focus-visible flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-ink transition-colors hover:bg-muted disabled:opacity-40 sm:hidden"
                  >
                    <Download className="h-4 w-4" />{t("agent.exportChat")}
                  </button>
                )}

                <MenuItem
                  icon={<Target className="h-3.5 w-3.5" />}
                  iconClass="bg-warning/12 text-warning"
                  title={t("agent.researchGoal")}
                  description="Mục tiêu nghiên cứu đa bước"
                  onClick={() => {
                    setShowUploadMenu(false);
                    onStartGoal();
                    inputRef.current?.focus();
                  }}
                />

                <MenuItem
                  icon={<Users className="h-3.5 w-3.5" />}
                  iconClass="bg-info/12 text-info"
                  title={t("agent.agentSwarm")}
                  description="Phối hợp đội ngũ chuyên gia AI"
                  onClick={() => {
                    setShowUploadMenu(false);
                    onStartSwarm();
                    inputRef.current?.focus();
                  }}
                />

                <div className="my-1 h-px bg-hairline-subtle" />

                <MenuItem
                  icon={<Landmark className="h-3.5 w-3.5" />}
                  iconClass="bg-success/12 text-success"
                  title={t("agent.checkConnector")}
                  description="Kiểm tra kết nối broker & sàn"
                  onClick={() => {
                    setShowUploadMenu(false);
                    submitPrompt(CONNECTOR_CHECK_PROMPT);
                  }}
                />

                <MenuItem
                  icon={<Landmark className="h-3.5 w-3.5" />}
                  iconClass="bg-success/12 text-success"
                  title={t("agent.analyzePortfolio")}
                  description="Đánh giá rủi ro danh mục"
                  onClick={() => {
                    setShowUploadMenu(false);
                    submitPrompt(CONNECTOR_PORTFOLIO_PROMPT);
                  }}
                />
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

          <div className="ms-auto flex min-w-0 items-center justify-end gap-1">
            {controls}
          </div>

          {/* Export Button */}
          {showExport && (
            <button
              type="button"
              onClick={onExport}
              disabled={!canExport}
              className="vt-focus-visible hidden h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-muted hover:text-ink disabled:opacity-20 sm:flex"
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
              className="vt-focus-visible flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-danger text-white transition-all hover:brightness-110 active:scale-95 shadow-sm"
              title={t("agent.stopGeneration")}
              aria-label={t("agent.stopGeneration")}
            >
              <Square className="h-3 w-3 fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={uploading || (goalComposerActive ? !input.trim() : (!input.trim() && attachments.length === 0))}
              className="vt-focus-visible flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground transition-all hover:bg-accent-strong active:scale-95 disabled:opacity-30 disabled:hover:bg-accent shadow-sm"
              title={t("agent.send")}
              aria-label={t("agent.send")}
            >
              <ArrowUp className="h-4 w-4 stroke-[2.5]" />
            </button>
          )}
        </div>
      </div>
    </form>
  );
}));
