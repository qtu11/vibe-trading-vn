import { render, screen } from "@testing-library/react";
import { MarkdownContent } from "../MessageBubble";

vi.mock("../RunCompleteCard", () => ({ RunCompleteCard: () => null }));

it("withdraws the marker paragraph instead of rendering a broken number", async () => {
  render(
    <MarkdownContent content={"NPL từ (đã lược※) lên (đã lược※).\n\n※ Đã lược bỏ 2 giá trị không khớp với dữ liệu công cụ của phiên này."} />,
  );
  expect(await screen.findByText(/Some figures in this older answer could not be verified/)).toBeInTheDocument();
  expect(screen.queryByText(/NPL từ/)).not.toBeInTheDocument();
  expect(screen.queryByText(/đã lược※/)).not.toBeInTheDocument();
  expect(screen.getByText(/※ Đã lược bỏ 2 giá trị/)).toBeInTheDocument();
});

it("renders a clean answer without a withdrawal notice", async () => {
  render(<MarkdownContent content={"Doanh thu tăng 12% so với cùng kỳ."} />);
  expect(await screen.findByText(/Doanh thu tăng 12%/)).toBeInTheDocument();
  expect(screen.queryByText(/could not be verified/)).not.toBeInTheDocument();
});
