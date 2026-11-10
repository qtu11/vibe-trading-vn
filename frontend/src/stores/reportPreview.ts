import { create } from "zustand";
import type { ReportEngineJob } from "@/lib/reportEngine";
import { evidenceUrl } from "@/lib/research";

/**
 * One open preview.
 *
 * The selection is discriminated by ``kind`` so the panel that renders it
 * can narrow the union without a cast. The store's `open*` functions build
 * these, so a caller never constructs one by hand.
 */
export type ReportSelection =
  | { kind: "report"; job?: ReportEngineJob; reportId?: string }
  | { kind: "source"; sourceUrl: string; title: string }
  | { kind: "research"; research: ResearchArtifact };

/** An AI-search result: the model's own synthesis plus the sources behind it. */
export interface ResearchArtifact {
  /** The query the research ran for. */
  query: string;
  /** The AI-written synthesis, when the tool produced one. */
  summary_markdown?: string;
  /** The collected sources. */
  sources: ResearchSource[];
  /** Which tool produced it. */
  tool?: string;
}

export interface ResearchSource {
  title: string;
  url: string;
  snippet?: string;
  publisher?: string;
}

export type PreviewKind = "report" | "source" | "research";

/** One open preview. `id` is stable for the life of the tab. */
export interface PreviewTab {
  id: string;
  kind: PreviewKind;
  title: string;
  selection: ReportSelection;
}

function jobTitle(job: ReportEngineJob): string {
  return job.artifacts[0]?.filename || job.job_id || "Báo cáo nghiên cứu";
}
/**
 * View state only: document handles are never persisted across chat sessions.
 *
 * The store holds a LIST of open previews, not one. A single slot made every
 * new preview replace the previous one, so the pane could only ever show one
 * tab: open a source and the report vanished, open the report and the source
 * vanished. Users asked for several artifacts side by side -- the research
 * document, the pages it cites, the AI search result that produced them.
 */
export const useReportPreviewStore = create<{
  tabs: PreviewTab[];
  activeId: string | null;
  openJob: (job: ReportEngineJob) => void;
  openArtifact: (reportId: string) => void;
  openSource: (url: string, title?: string) => void;
  openResearch: (artifact: ResearchArtifact) => void;
  setActive: (id: string) => void;
  closeTab: (id: string) => void;
  close: () => void;
}>((set, get) => ({
  tabs: [],
  activeId: null,

  openJob: (job) => {
    const id = `job:${job.job_id}`;
    const tab: PreviewTab = { id, kind: "report", title: jobTitle(job), selection: { kind: "report", job } };
    set((state) => {
      const existing = state.tabs.find((item) => item.id === id);
      if (existing) return { activeId: id };
      return { tabs: [...state.tabs, tab], activeId: id };
    });
  },

  openArtifact: (reportId) => {
    const id = `artifact:${reportId}`;
    set((state) => {
      const existing = state.tabs.find((item) => item.id === id);
      if (existing) return { activeId: id };
      const tab: PreviewTab = { id, kind: "report", title: "Báo cáo nghiên cứu", selection: { kind: "report", reportId } };
      return { tabs: [...state.tabs, tab], activeId: id };
    });
  },

  openSource: (url, title) => {
    const safe = evidenceUrl(url);
    if (!safe) return;
    const id = `source:${safe}`;
    set((state) => {
      const existing = state.tabs.find((item) => item.id === id);
      if (existing) return { activeId: id };
      const tab: PreviewTab = {
        id,
        kind: "source",
        title: title || new URL(safe).hostname,
        selection: { kind: "source", sourceUrl: safe, title: title || new URL(safe).hostname },
      };
      return { tabs: [...state.tabs, tab], activeId: id };
    });
  },

  openResearch: (artifact) => {
    const query = artifact.query?.trim();
    const id = `research:${query || artifact.sources.map((source) => source.url).join("|")}`;
    set((state) => {
      const existing = state.tabs.find((item) => item.id === id);
      if (existing) return { activeId: id };
      const tab: PreviewTab = {
        id,
        kind: "research",
        title: query ? `Nghiên cứu: ${query}` : "Kết quả AI research",
        selection: { kind: "research", research: artifact },
      };
      return { tabs: [...state.tabs, tab], activeId: id };
    });
  },

  setActive: (id) => {
    if (get().tabs.some((tab) => tab.id === id)) set({ activeId: id });
  },

  closeTab: (id) => {
    set((state) => {
      const index = state.tabs.findIndex((tab) => tab.id === id);
      if (index < 0) return state;
      const tabs = state.tabs.filter((tab) => tab.id !== id);
      if (state.activeId !== id) return { tabs, activeId: state.activeId };
      // Closing the active tab hands focus to a neighbour, never to nothing
      // while other tabs remain.
      const next = tabs[index] ?? tabs[index - 1] ?? null;
      return { tabs, activeId: next?.id ?? null };
    });
  },

  close: () => {
    set({ tabs: [], activeId: null });
  },
}));
