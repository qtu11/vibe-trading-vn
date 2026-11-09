import { parseSourceCitations, sourceReferencesMarkdown, sourceResolutionMarkdown } from "../sourceEvidence";

function source(overrides: Record<string, unknown> = {}) {
  return parseSourceCitations([{ source_id: "S1", title: "Báo cáo FPT", url: "https://example.com/report", publisher: "FPT", published_at: "2026-03-30", ...overrides }])[0];
}

it("exports an alphabetized APA list, deduplicating URLs without assuming the publisher is the author", () => {
  const references = sourceReferencesMarkdown([source(), source(), source({ title: "ABC", url: "https://example.com/abc", published_at: null, retrieved_at: "2026-11-08" })]);
  expect(references).toContain("*Báo cáo FPT*. (2026, March 30). FPT. [https://example.com/report](https://example.com/report)");
  expect(references).toContain("*ABC*. (n.d.). FPT.");
  expect(references.indexOf("*ABC*")).toBeLessThan(references.indexOf("*Báo cáo FPT*"));
  expect(references.match(/\*Báo cáo FPT\*/g)).toHaveLength(1);
  expect(references).not.toContain("November 8");
});

it("preserves the per-turn S1 mapping even when another turn reuses S1", () => {
  expect(sourceResolutionMarkdown([source()])).toBe("[S1](https://example.com/report)");
  expect(sourceResolutionMarkdown([source({ url: "https://example.com/other" })])).toBe("[S1](https://example.com/other)");
  expect(sourceReferencesMarkdown([source(), source({ url: "https://example.com/other" })]).match(/\*Báo cáo FPT\*/g)).toHaveLength(2);
});

it("does not create citations from forbidden links, credentials or disallowed sources", () => {
  const rows = [source({ url: "javascript:alert(1)" }), source({ url: "https://user:password@example.com/x" }), source({ cite_allowed: false })];
  expect(sourceReferencesMarkdown(rows)).toBe("");
  expect(sourceResolutionMarkdown(rows)).toBe("");
});

it("escapes metadata and handles missing or invalid publication dates without inventing them", () => {
  const result = sourceReferencesMarkdown([source({ title: "[Forged](javascript:alert(1))\n# title", url: "https://example.com/a(b)", published_at: "2026-02-30" })]);
  expect(result).toContain("(n.d.)");
  expect(result).toContain("https://example.com/a%28b%29");
  expect(result).toContain("\\[Forged\\]");
  expect(result).not.toContain("\n# title");
});
