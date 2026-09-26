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
