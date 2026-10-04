import type { Citation, ExperimentSummary, HeadlineMetric } from "@/lib/api/types";

const LANGUAGES: Record<string, string> = {
  en: "English",
  hi: "Hindi",
  "hi-Latn": "Hinglish",
  ta: "Tamil",
  "ta-Latn": "Tamil (romanised)",
};

export function languageName(code: string | null): string | null {
  if (code === null) return null;
  return LANGUAGES[code] ?? code;
}

export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

export function formatDuration(startIso: string, endIso: string | null): string | null {
  if (endIso === null) return null;
  const minutes = Math.round((Date.parse(endIso) - Date.parse(startIso)) / 60_000);
  if (minutes < 1) return "under a minute";
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

export function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

// What the mentor did, told to the student — and the same tools named plainly for admins.
const TOOLS: Record<string, { activity: string; name: string }> = {
  search_knowledge: { activity: "Searched your course material", name: "Course search" },
  get_student_progress: { activity: "Checked your progress", name: "Read progress" },
  update_student_progress: { activity: "Updated your progress", name: "Update progress" },
  create_study_plan: { activity: "Made a study plan", name: "Create study plan" },
  get_study_plan: { activity: "Opened your study plan", name: "Read study plan" },
  generate_quiz: { activity: "Made a quiz", name: "Generate quiz" },
  retrieve_previous_conversation: {
    activity: "Looked back at an earlier session",
    name: "Recall past session",
  },
};

export const toolActivityLabel = (tool: string) => TOOLS[tool]?.activity ?? tool;
export const toolName = (tool: string) => TOOLS[tool]?.name ?? tool;

/** Stat-tile figures: exact below 10,000 (1,284), compact above (12.9K). */
export function formatCount(value: number): string {
  return new Intl.NumberFormat(undefined, value < 10_000 ? {} : { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

/** "KVL Notes — Unit 7 › 7.1 KVL — p. 12": the document, where in it, and the pages, if known. */
export function describeCitation(citation: Citation): string {
  const where = citation.heading_path ?? citation.section;
  const pages =
    citation.page_start === null
      ? null
      : citation.page_end !== null && citation.page_end !== citation.page_start
        ? `pp. ${citation.page_start}–${citation.page_end}`
        : `p. ${citation.page_start}`;
  return [citation.document_title, where, pages].filter(Boolean).join(" — ");
}

/** A run's headline number as the suite reports it: 0.893, 575 ms, 14 / 14. */
export function formatHeadline(metric: HeadlineMetric): string {
  const value =
    metric.unit === "ms"
      ? formatMs(metric.value)
      : metric.unit === "ratio"
        ? metric.value.toFixed(3)
        : formatCount(metric.value);
  return metric.of !== null && metric.unit === "count" ? `${value} / ${formatCount(metric.of)}` : value;
}

const DECISIONS: Record<string, string> = {
  adopt: "Adopted",
  reject: "Rejected",
  inconclusive: "Inconclusive",
  pending: "Pending",
};

export const decisionLabel = (decision: string) => DECISIONS[decision] ?? decision;

const signed = (value: number, digits: number) =>
  `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}`;

/**
 * "endpoint_ms 575.3 → 348.1 over 36 cases; gain +227.2 (95% CI +217.2 to +237.2)". The gain is
 * in the metric's own units and positive means better, whichever way the metric points.
 */
export function describeComparison(e: ExperimentSummary): string | null {
  if (e.metric === null || e.baseline_mean === null || e.candidate_mean === null) return null;
  const digits = Math.abs(e.baseline_mean) >= 10 ? 1 : 3;
  const parts = [
    `${e.metric} ${e.baseline_mean.toFixed(digits)} → ${e.candidate_mean.toFixed(digits)} over ${e.cases} cases`,
  ];
  if (e.mean_gain !== null) {
    const ci = e.gain_95ci ? ` (95% CI ${signed(e.gain_95ci[0], digits)} to ${signed(e.gain_95ci[1], digits)})` : "";
    parts.push(`gain ${signed(e.mean_gain, digits)}${ci}`);
  }
  return parts.join("; ");
}

/** The short form of a content digest or commit: enough to tell two apart, not to verify one. */
export const shortHash = (hash: string) => hash.slice(0, 12);
