import { create } from "zustand";
import type { ReportEngineJob } from "@/lib/reportEngine";

type ReportSelection = { job: ReportEngineJob } | { reportId: string };

/** View state only: document handles are never persisted across chat sessions. */
export const useReportPreviewStore = create<{
  selection: ReportSelection | null;
  openJob: (job: ReportEngineJob) => void;
  openArtifact: (reportId: string) => void;
  close: () => void;
}>((set) => ({
  selection: null,
  openJob: (job) => set({ selection: { job } }),
  openArtifact: (reportId) => set({ selection: { reportId } }),
  close: () => set({ selection: null }),
}));
