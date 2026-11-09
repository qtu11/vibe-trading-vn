import { describe, expect, it } from "vitest";
import {
  hasLegacyGroundingMarker,
  withdrawLegacyGrounding,
} from "../legacyGrounding";

const NOTICE = /Some figures in this older answer could not be verified/;

describe("hasLegacyGroundingMarker", () => {
  it("recognizes every released marker spelling", () => {
    expect(hasLegacyGroundingMarker("(đã lược※)")).toBe(true);
    expect(hasLegacyGroundingMarker("(omitted※)")).toBe(true);
    expect(hasLegacyGroundingMarker("（略※）")).toBe(true);
    expect(hasLegacyGroundingMarker("doanh thu tăng 12%")).toBe(false);
  });
});

describe("withdrawLegacyGrounding", () => {
  it("leaves a clean answer untouched", () => {
    const content = "Doanh thu tăng 12%.\n\n| Chỉ tiêu | Giá trị |\n| --- | --- |\n| ROE | 18% |";
    expect(withdrawLegacyGrounding(content)).toEqual({ content, withheld: false });
  });

  it("withdraws the paragraph that carries the marker and adds one notice", () => {
    const result = withdrawLegacyGrounding(
      "Mở đầu.\n\nNPL từ (đã lược※) lên (đã lược※).\n\nKết luận giữ nguyên.",
    );

    expect(result.withheld).toBe(true);
    expect(result.content).not.toContain("đã lược※");
    expect(result.content).not.toContain("NPL từ");
    expect(result.content).toContain("Mở đầu.");
    expect(result.content).toContain("Kết luận giữ nguyên.");
    expect(result.content.match(/Some figures in this older answer/g)).toHaveLength(1);
    expect(result.content).toMatch(NOTICE);
  });

  it("keeps a heading when the withdrawn paragraph is a separate block", () => {
    const result = withdrawLegacyGrounding(
      "## Định giá\n\nP/E hiện tại là (đã lược※)x.",
    );

    expect(result.content).not.toContain("## Định giá");
    expect(result.content).not.toContain("P/E");
  });

  it("drops only the marked data rows of a table", () => {
    const result = withdrawLegacyGrounding(
      [
        "| Chỉ tiêu | Giá trị |",
        "| --- | --- |",
        "| Doanh thu | 1.000 tỷ |",
        "| NPL | (đã lược※) |",
        "| ROE | 18% |",
      ].join("\n"),
    );

    expect(result.withheld).toBe(true);
    expect(result.content).toContain("| Doanh thu | 1.000 tỷ |");
    expect(result.content).toContain("| ROE | 18% |");
    expect(result.content).not.toContain("NPL");
    expect(result.content).not.toContain("đã lược※");
    expect(result.content).toContain("| Chỉ tiêu | Giá trị |");
  });

  it("drops the whole table when every data row is marked", () => {
    const result = withdrawLegacyGrounding(
      ["| Chỉ tiêu | Giá trị |", "| --- | --- |", "| NPL | (đã lược※) |"].join("\n"),
    );

    expect(result.withheld).toBe(true);
    expect(result.content).not.toContain("Chỉ tiêu");
    expect(result.content).not.toContain("đã lược※");
    expect(result.content).toMatch(NOTICE);
  });

  it("drops figures and non-chart code fences that expose a marker", () => {
    const result = withdrawLegacyGrounding(
      [
        "Giữ đoạn này.",
        "",
        "```figures",
        '[{"label":"NPL","value":"(đã lược※)"}]',
        "```",
        "",
        "```json",
        '{"roe":"(đã lược※)"}',
        "```",
      ].join("\n"),
    );

    expect(result.withheld).toBe(true);
    expect(result.content).toContain("Giữ đoạn này.");
    expect(result.content).not.toContain("```figures");
    expect(result.content).not.toContain('"label":"NPL"');
    expect(result.content).not.toContain("đã lược※");
  });

  it("keeps a chart fence for ChartBlock's legacy state", () => {
    const chart = '```chart\n{"symbol":"MBB.VN","as_of":"2025-11-(đã lược※)","bars":[]}\n```';
    const content = `Mở đầu.\n\n${chart}`;
    const result = withdrawLegacyGrounding(content);

    // ChartBlock renders the fence itself and shows its own legacy state, so
    // the markdown sanitizer must not strip the payload before it gets there.
    expect(result.withheld).toBe(false);
    expect(result.content).toBe(content);
  });

  it("returns only the notice when every block is withdrawn", () => {
    const result = withdrawLegacyGrounding("NPL từ (đã lược※) lên (đã lược※).");

    expect(result.withheld).toBe(true);
    expect(result.content.startsWith("> ")).toBe(true);
    expect(result.content).toMatch(NOTICE);
  });
});
