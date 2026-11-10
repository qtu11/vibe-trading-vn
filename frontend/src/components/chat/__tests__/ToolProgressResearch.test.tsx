import { act, fireEvent, render, screen } from "@testing-library/react";
import { ToolProgressIndicator } from "../ToolProgressIndicator";
import { PreviewPane } from "../PreviewPane";
import { buildToolTimelineMessages } from "@/pages/agentToolTimeline";
import { useReportPreviewStore } from "@/stores/reportPreview";

vi.mock("@/lib/api", () => ({
  api: { getReportJobForArtifact: vi.fn(), getReportPreviewPages: vi.fn() },
  downloadGeneratedReport: vi.fn(),
  fetchReportPreviewPage: vi.fn(),
}));

const research = {
  tool: "parallel_web_search",
  query: "VIC Q3 2026",
  summary_markdown: "### Tổng hợp kết quả",
  sources: [{ url: "https://example.com/a", title: "Nguồn A", source_id: "S17" }],
};

beforeEach(() => {
  useReportPreviewStore.getState().close();
});

describe("a reloaded session can still open its AI-search result", () => {
  it("offers the result on a search row rebuilt from the persisted trail", () => {
    // The persisted trail is what a reloaded session hydrates from. Without
    // the research payload the row rendered again with no way to open it,
    // so the right-hand pane stayed empty.
    const [message] = buildToolTimelineMessages(
      [{
        tool: "parallel_web_search",
        call_id: "call-search-1",
        arguments: { query: "VIC Q3 2026" },
        status: "ok",
        elapsed_ms: 3000,
        preview: '{"status": "ok"}',
        research,
        timestamp: 1_785_342_400_000,
      }],
      { fallbackTimestamp: 1_785_342_500_000, attemptId: "attempt-1" },
    );

    render(<ToolProgressIndicator toolCalls={message.meta!.activity!.steps} />);

    expect(screen.getByRole("button", { name: /Mở kết quả AI research/i })).toBeVisible();
  });

  it("opens the result in the right-hand pane when the link is clicked", () => {
    const [message] = buildToolTimelineMessages(
      [{
        tool: "parallel_web_search",
        call_id: "call-search-1",
        arguments: { query: "VIC Q3 2026" },
        status: "ok",
        elapsed_ms: 3000,
        preview: '{"status": "ok"}',
        research,
        timestamp: 1_785_342_400_000,
      }],
      { fallbackTimestamp: 1_785_342_500_000, attemptId: "attempt-1" },
    );

    render(
      <>
        <ToolProgressIndicator toolCalls={message.meta!.activity!.steps} />
        <PreviewPane />
      </>,
    );

    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Mở kết quả AI research/i }));

    act(() => undefined);

    // The pane opened with the research, not an empty box.
    expect(screen.getByRole("complementary", { name: "VIC Q3 2026" })).toBeVisible();
    expect(screen.getByText("Tổng hợp kết quả")).toBeVisible();
    expect(screen.getByRole("link", { name: /Nguồn A/ })).toBeVisible();
    expect(screen.getByText("[S17]")).toBeVisible();
  });

  it("offers nothing on a search row that carried no result", () => {
    render(
      <ToolProgressIndicator
        toolCalls={[{
          id: "call-1",
          tool: "parallel_web_search",
          arguments: {},
          status: "ok",
          timestamp: 1_785_342_400_000,
        }]}
      />,
    );

    expect(screen.queryByRole("button", { name: /Mở kết quả AI research/i })).not.toBeInTheDocument();
  });
});
