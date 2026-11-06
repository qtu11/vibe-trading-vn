import { act, fireEvent, render, screen } from "@testing-library/react";
import { api, downloadResearchMarkdown } from "@/lib/api";
import { ResearchReportExport } from "../ResearchReportExport";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/lib/api", () => ({ api: { researchRevisionReport: vi.fn() }, downloadResearchMarkdown: vi.fn() }));
beforeEach(() => vi.clearAllMocks());
const id = "rr_" + "a".repeat(32);
const report = "# Báo cáo nháp\n\nNguồn chưa xác minh.\n\n| Chỉ số | Giá trị |\n|---|---|\n| Tiền | 0 |\n";

it("previews only on demand then downloads the exact fetched body without a second request", async () => {
  vi.mocked(api.researchRevisionReport).mockResolvedValue(report);
  render(<ResearchReportExport revisionId={id} disabled={false} />);
  expect(api.researchRevisionReport).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "researchRevision.reportDownload" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.reportRead" }));
  expect(await screen.findByRole("heading", { name: "Báo cáo nháp" })).toBeVisible();
  expect(screen.getByRole("cell", { name: "0" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.reportDownload" }));
  expect(downloadResearchMarkdown).toHaveBeenCalledExactlyOnceWith(id, report);
  expect(api.researchRevisionReport).toHaveBeenCalledTimes(1);
});

it("does not render remote images or executable source links from a report body", async () => {
  vi.mocked(api.researchRevisionReport).mockResolvedValue('# Source\n\n<img src="https://example.com/leak"/>\n\n![remote](https://example.com/tracker)\n\n[bad](javascript:alert(1))\n\n[safe](https://example.com/filing)');
  render(<ResearchReportExport revisionId={id} disabled={false} />);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.reportRead" }));
  await screen.findByRole("heading", { name: "Source" });
  expect(document.querySelector("img")).toBeNull();
  expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
  expect(screen.getByRole("link", { name: "safe" })).toHaveAttribute("rel", "noopener noreferrer");
});

it("aborts and ignores the previous revision report after selection changes", async () => {
  let resolve!: (value: string) => void;
  vi.mocked(api.researchRevisionReport).mockImplementation(() => new Promise((done) => { resolve = done; }));
  const { rerender } = render(<ResearchReportExport revisionId={id} disabled={false} />);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.reportRead" }));
  const signal = vi.mocked(api.researchRevisionReport).mock.calls[0][1]!;
  rerender(<ResearchReportExport revisionId={"rr_" + "b".repeat(32)} disabled={false} />);
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(report));
  expect(screen.queryByRole("heading", { name: "Báo cáo nháp" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "researchRevision.reportDownload" })).toBeDisabled();
});

it("shows errors without inferring an empty report or retrying", async () => {
  vi.mocked(api.researchRevisionReport).mockRejectedValue(new Error("Integrity failed"));
  render(<ResearchReportExport revisionId={id} disabled={false} />);
  fireEvent.click(screen.getByRole("button", { name: "researchRevision.reportRead" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Integrity failed");
  expect(screen.getByRole("button", { name: "researchRevision.reportDownload" })).toBeDisabled();
  expect(api.researchRevisionReport).toHaveBeenCalledTimes(1);
});
