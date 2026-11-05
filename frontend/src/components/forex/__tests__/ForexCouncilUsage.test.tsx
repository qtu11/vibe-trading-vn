import { render, screen } from "@testing-library/react";
import { ForexCouncilUsage } from "../ForexCouncilUsage";
import i18n from "@/i18n";

beforeAll(async () => { await i18n.changeLanguage("en"); });

it("shows unknown per-role usage as missing rather than zero tokens", () => {
  render(<ForexCouncilUsage usage={{ scope: "forex_council", attempted_calls: 1, reported_calls: 0, missing_calls: 1,
    totals: null, per_role: [{ role: "risk", usage: null }] }} />);
  expect(screen.getByText(/risk: ↑— ↓—/)).toBeInTheDocument();
  expect(screen.getByText(/unknown usage/)).toBeInTheDocument();
});

it("does not add cache tokens to reported input", () => {
  render(<ForexCouncilUsage usage={{ scope: "forex_council", attempted_calls: 1, reported_calls: 1, missing_calls: 0,
    totals: { input_tokens: 600, output_tokens: 100, cache_read_tokens: 360 },
    per_role: [{ role: "technical", usage: { input_tokens: 600, output_tokens: 100 } }] }} />);
  expect(screen.getByText("Input 600 · Output 100 · Cache 360")).toBeInTheDocument();
  expect(screen.getByText(/subset of input/)).toBeInTheDocument();
});
