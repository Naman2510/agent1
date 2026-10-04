import { describe, expect, it } from "vitest";

import type { Citation, ExperimentSummary } from "@/lib/api/types";
import { decisionLabel, describeCitation, describeComparison, formatHeadline } from "@/lib/format";

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

describe("formatHeadline", () => {
  const metric = { key: "k", label: "l", of: null };
  it("shows a ratio to three places, a time in ms, and a count out of its total", () => {
    expect(formatHeadline({ ...metric, unit: "ratio", value: 0.89263 })).toBe("0.893");
    expect(formatHeadline({ ...metric, unit: "ms", value: 575.3 })).toBe("575 ms");
    expect(formatHeadline({ ...metric, unit: "count", value: 14, of: 14 })).toBe("14 / 14");
    expect(formatHeadline({ ...metric, unit: "count", value: 0 })).toBe("0");
  });
});

describe("describeComparison", () => {
  const exp: ExperimentSummary = {
    slug: "EXP-003",
    title: "t",
    hypothesis: "h",
    suite: "voice",
    variable_changed: "session.semantic_endpointing",
    decision: "reject",
    rationale: null,
    decided_at: null,
    baseline_run_id: null,
    candidate_run_id: null,
    metric: "endpoint_ms",
    cases: 36,
    baseline_mean: 575.2778,
    candidate_mean: 348.0556,
    mean_gain: 227.2222,
    gain_95ci: [217.2222, 237.2222],
    guards: [],
  };

  it("states the change, the gain and its interval in the metric's own units", () => {
    expect(describeComparison(exp)).toBe(
      "endpoint_ms 575.3 → 348.1 over 36 cases; gain +227.2 (95% CI +217.2 to +237.2)",
    );
  });

  it("keeps small metrics at three places, and a loss signed as one", () => {
    expect(
      describeComparison({ ...exp, metric: "ndcg@10", baseline_mean: 0.8748, candidate_mean: 0.8926, mean_gain: 0.0179, gain_95ci: [-0.0017, 0.0533] }),
    ).toBe("ndcg@10 0.875 → 0.893 over 36 cases; gain +0.018 (95% CI −0.002 to +0.053)");
  });

  it("says nothing it does not know", () => {
    expect(describeComparison({ ...exp, metric: null })).toBeNull();
  });
});

describe("decisionLabel", () => {
  it("names each decision plainly", () => {
    expect(decisionLabel("reject")).toBe("Rejected");
    expect(decisionLabel("inconclusive")).toBe("Inconclusive");
  });
});
