import i18n from "@/i18n";

/**
 * Omission marks written by older grounding releases. A marker is a hole where
 * an unverified number used to be; keeping it in the answer leaves broken
 * fragments such as "—x", "— YoY" or "≈ —x" on screen.
 */
const LEGACY_MARKER_RE = /\((?:đã lược|omitted)※\)|（略※）/i;

export function hasLegacyGroundingMarker(text: string): boolean {
  return LEGACY_MARKER_RE.test(text);
}

type Block =
  | { kind: "fence"; text: string; language: string }
  | { kind: "text"; text: string }
  | { kind: "blank"; text: string };

/** Split markdown into fences, blank lines and prose blocks without parsing it. */
function splitBlocks(content: string): Block[] {
  const lines = content.split("\n");
  const blocks: Block[] = [];
  let buffer: string[] = [];

  const flush = () => {
    if (!buffer.length) return;
    blocks.push({ kind: "text", text: buffer.join("\n") });
    buffer = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const opener = /^\s*```\s*([^\s`]*)/.exec(line);
    if (opener) {
      flush();
      const start = index;
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
        index += 1;
      }
      blocks.push({
        kind: "fence",
        text: lines.slice(start, index + 1).join("\n"),
        language: (opener[1] || "").toLowerCase(),
      });
      continue;
    }
    if (!line.trim()) {
      flush();
      blocks.push({ kind: "blank", text: line });
      continue;
    }
    buffer.push(line);
  }

  flush();
  return blocks;
}

function isHeading(text: string): boolean {
  const trimmed = text.trim();
  return !trimmed.includes("\n") && /^#{1,6}\s+\S/.test(trimmed);
}

/**
 * Withdraw a marked paragraph, or only the marked data rows of a table.
 *
 * A table keeps its header and separator when at least one data row survives;
 * otherwise the whole table goes. A paragraph, list or heading block has no
 * safe partial form, so it is removed as a unit.
 */
function sanitizeTextBlock(text: string): { text: string | null; table: boolean } {
  if (!hasLegacyGroundingMarker(text)) return { text, table: false };

  const rows = text.split("\n").filter((line) => line.trim());
  const isTable = rows.length > 0 && rows.every((line) => line.trimStart().startsWith("|"));
  if (!isTable) return { text: null, table: false };
  if (rows.length <= 2) return { text: null, table: true };

  const header = rows.slice(0, 2);
  if (header.some((line) => hasLegacyGroundingMarker(line))) {
    return { text: null, table: true };
  }
  const kept = rows.filter(
    (line, index) => index < 2 || !hasLegacyGroundingMarker(line),
  );
  return kept.length > 2
    ? { text: kept.join("\n"), table: true }
    : { text: null, table: true };
}

export interface LegacyGroundingResult {
  content: string;
  withheld: boolean;
}

/**
 * Remove legacy release markers and the prose/rows that depend on them.
 *
 * Stored answers written before the current release pipeline can still carry
 * `(đã lược※)`, `(omitted※)` or `（略※）`. Rendering those markers preserves a
 * broken number's unit without its value, so the renderer withdraws the
 * dependent paragraph or table row and adds one localized notice instead.
 */
export function withdrawLegacyGrounding(content: string): LegacyGroundingResult {
  if (!hasLegacyGroundingMarker(content)) return { content, withheld: false };

  const kept: Block[] = [];
  let withheld = false;

  for (const block of splitBlocks(content)) {
    if (block.kind === "fence") {
      if (block.language === "figures") {
        withheld = true;
        continue;
      }
      // A chart fence is parsed by ChartBlock, which never prints its raw JSON.
      // Other fences would expose the marker, so they are withdrawn entirely.
      if (block.language !== "chart" && hasLegacyGroundingMarker(block.text)) {
        withheld = true;
        continue;
      }
      kept.push(block);
      continue;
    }
    if (block.kind === "blank") {
      kept.push(block);
      continue;
    }

    const result = sanitizeTextBlock(block.text);
    if (result.text === null) {
      withheld = true;
      // A heading often states the conclusion the withdrawn paragraph was
      // meant to establish; it cannot survive that evidence.
      let previous = kept.length - 1;
      while (previous >= 0 && kept[previous].kind === "blank") previous -= 1;
      if (
        previous >= 0
        && kept[previous].kind === "text"
        && isHeading(kept[previous].text)
      ) {
        kept.splice(previous, 1);
      }
      continue;
    }
    if (result.text !== block.text) withheld = true;
    kept.push({ kind: "text", text: result.text });
  }

  if (!withheld) return { content, withheld: false };

  const body = kept
    .map((block) => block.text)
    .join("\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  const notice = `> ${i18n.t("messageBubble.legacyWithheld")}`;
  return { content: body ? `${body}\n\n${notice}` : notice, withheld: true };
}
