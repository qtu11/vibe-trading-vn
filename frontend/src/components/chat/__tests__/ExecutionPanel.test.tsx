import { render, screen } from "@testing-library/react";
import { ExecutionPanel } from "../ExecutionPanel";
import { classifyToolPhase, groupStepsIntoPhases } from "../executionPhases";
import type { ToolCallEntry } from "@/types/agent";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../ToolProgressIndicator", () => ({ ToolProgressIndicator: () => null }));

function step(tool: string, status: ToolCallEntry["status"]): ToolCallEntry {
  return { id: tool, tool, status, arguments: {}, timestamp: 0 };
}

it("counts failed calls across phases consistently with each phase's error count", () => {
  render(<ExecutionPanel toolCalls={[step("read_url", "error"), step("get_market_data", "error"), step("vietnam_comparables", "error")]} />);
  expect(screen.getByText("3 execution.failedPhases")).toBeInTheDocument();
});

it("keeps a phase running while another call has failed and groups scrapes with collection", () => {
  expect(classifyToolPhase("concurrent_scraper")).toBe("collection");
  const [group] = groupStepsIntoPhases([step("read_url", "error"), step("concurrent_scraper", "running")]);
  expect(group).toMatchObject({ id: "collection", errors: 1, status: "running" });
});
