import { create } from "zustand";
import type { ReportEngineJob } from "@/lib/reportEngine";
import { evidenceUrl } from "@/lib/research";

type ReportSelection = { job: ReportEngineJob } | { reportId: string } | { sourceUrl: string; title: string };

/** View state only: document handles are never persisted across chat sessions. */
export const useReportPreviewStore = create<{
  selection: ReportSelection | null;
  openJob: (job: ReportEngineJob) => void;
  openArtifact: (reportId: string) => void;
  openSource: (url: string, title?: string) => void;
  close: () => void;
}>((set) => ({
  selection: null,
  openJob: (job) => set({ selection: { job } }),
  openArtifact: (reportId) => set({ selection: { reportId } }),
  openSource: (url, title) => {
    const safe = evidenceUrl(url);
    if (safe) set({ selection: { sourceUrl: safe, title: title || new URL(safe).hostname } });
  },
  close: () => set({ selection: null }),
}));
