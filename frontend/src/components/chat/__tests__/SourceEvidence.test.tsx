import { render, screen } from "@testing-library/react";
import { MessageBubble } from "../MessageBubble";
import { SourceEvidence } from "../SourceEvidence";
import { parseSourceCitations } from "@/lib/sourceEvidence";
import type { StoredAgentMessage } from "@/stores/agent";

vi.mock("react-markdown", () => ({
  default: ({ children }: { children: string }) => <div data-testid="markdown">{children}</div>,
}));
vi.mock("remark-gfm", () => ({ default: () => {} }));
vi.mock("rehype-highlight", () => ({ default: () => {} }));

function sourceRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    source_id: "S1",
    title: "Báo cáo thường niên FPT 2025",
    url: "https://fpt.com.vn/bao-cao-thuong-nien",
    domain: "fpt.com.vn",
    publisher: "FPT",
    tier: 1,
    tier_label: "official/primary",
    market: ["VN"],
    published_at: "2026-03-30",
    data_effective_at: "2025-12-31",
    data_effective_basis: "explicit",
    retrieved_at: "2026-11-06T03:00:00Z",
    verification: "unverified",
    cite_allowed: true,
    ...overrides,
  };
}

function makeMsg(overrides: Partial<StoredAgentMessage> = {}): StoredAgentMessage {
  return {
    id: "msg-1",
    type: "answer",
    content: "Doanh thu 2025 đạt 70.000 tỷ [S1].",
    timestamp: 1,
    ...overrides,
  };
}

describe("parseSourceCitations", () => {
  it("keeps the fields a reader needs to judge a source", () => {
    const parsed = parseSourceCitations([sourceRow()]);

    expect(parsed).toHaveLength(1);
    expect(parsed[0]).toMatchObject({
      sourceId: "S1",
      tier: 1,
      tierLabel: "official/primary",
      publishedAt: "2026-03-30",
      dataEffectiveAt: "2025-12-31",
      dataEffectiveBasis: "explicit",
      verification: "unverified",
    });
  });

  it("drops malformed rows and unsafe links", () => {
    const parsed = parseSourceCitations([
      sourceRow({ source_id: "", title: "no id" }),
      sourceRow({ source_id: "S2", url: "javascript:alert(1)" }),
      "not a record",
    ]);

    expect(parsed.map((source) => source.sourceId)).toEqual(["S2"]);
    expect(parsed[0].url).toBeNull();
  });

  it("labels a publication-date fallback as a fallback", () => {
    const parsed = parseSourceCitations([
      sourceRow({
        data_effective_at: "2026-03-30",
        data_effective_basis: "published_at",
      }),
    ]);

    expect(parsed[0].dataEffectiveAt).toBe("2026-03-30");
    expect(parsed[0].dataEffectiveBasis).toBe("published_at");
  });

  it("returns an empty list for a missing or non-array field", () => {
    expect(parseSourceCitations(undefined)).toEqual([]);
    expect(parseSourceCitations({ sources: [] })).toEqual([]);
  });
});

describe("SourceEvidence", () => {
  it("renders the tier, timestamps and verification label", () => {
    render(<SourceEvidence sources={parseSourceCitations([sourceRow()])} />);

    expect(screen.getByText("Sources · Nguồn")).toBeInTheDocument();
    expect(screen.getByText("S1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Báo cáo thường niên FPT 2025/ })).toHaveAttribute(
      "href",
      "https://fpt.com.vn/bao-cao-thuong-nien",
    );
    expect(screen.getByText(/Tier 1 · official\/primary/)).toBeInTheDocument();
    expect(screen.getByText(/published 2026-03-30/)).toBeInTheDocument();
    expect(screen.getByText(/data effective 2025-12-31/)).toBeInTheDocument();
    expect(screen.getByText("unverified")).toBeInTheDocument();
  });

  it("marks the publication-date fallback instead of claiming an explicit as-of", () => {
    render(
      <SourceEvidence
        sources={parseSourceCitations([
          sourceRow({
            data_effective_at: "2026-03-30",
            data_effective_basis: "published_at",
          }),
        ])}
      />,
    );

    expect(screen.getByText(/publication fallback/)).toBeInTheDocument();
  });

  it("renders nothing when the ledger has no sources", () => {
    const { container } = render(<SourceEvidence sources={[]} />);

    expect(container).toBeEmptyDOMElement();
  });
});

describe("MessageBubble answer sources", () => {
  it("shows the [S#] resolution list under the answer", () => {
    render(
      <MessageBubble
        msg={makeMsg({ sources: parseSourceCitations([sourceRow()]) })}
      />,
    );

    expect(screen.getByText("Sources · Nguồn")).toBeInTheDocument();
    expect(screen.getByText("S1")).toBeInTheDocument();
  });

  it("does not invent a sources panel when metadata is absent", () => {
    render(<MessageBubble msg={makeMsg()} />);

    expect(screen.queryByText("Sources · Nguồn")).toBeNull();
  });
});
