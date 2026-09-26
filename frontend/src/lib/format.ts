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
