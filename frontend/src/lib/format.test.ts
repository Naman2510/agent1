import { describe, expect, it } from "vitest";

import type { Citation } from "@/lib/api/types";
import { describeCitation } from "@/lib/format";

const base: Citation = {
  ref: "[1]",
  document_title: "KVL Notes",
  heading_path: "Unit 7 › 7.1 KVL",
  section: "7.1",
  page_start: 12,
  page_end: 12,
};

describe("describeCitation", () => {
  it("names the document, where in it, and the page", () => {
    expect(describeCitation(base)).toBe("KVL Notes — Unit 7 › 7.1 KVL — p. 12");
  });

  it("gives a page range when the passage spans pages", () => {
    expect(describeCitation({ ...base, page_end: 14 })).toBe(
      "KVL Notes — Unit 7 › 7.1 KVL — pp. 12–14",
    );
  });

  it("falls back to the section number when there is no heading path", () => {
    expect(describeCitation({ ...base, heading_path: null })).toBe("KVL Notes — 7.1 — p. 12");
  });

  it("leaves out what is not known rather than inventing it", () => {
    expect(
      describeCitation({ ...base, heading_path: null, section: null, page_start: null, page_end: null }),
    ).toBe("KVL Notes");
  });
});
