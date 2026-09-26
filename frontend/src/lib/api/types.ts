// Mirrors of the backend's response models (backend/app/schemas). Kept by hand and small on
// purpose: the OpenAPI schema is the source of truth, and these cover only what the UI reads.

export type NotMeasured = "not_measured";

export interface StudentSummary {
  id: string;
  display_name: string;
  institution: string | null;
  semester: number | null;
  preferred_language: string;
  consent_audio_retention: boolean;
}

export interface Me {
  id: string;
  email: string;
  role: "student" | "admin" | string;
  student: StudentSummary | null;
}

/** What the auth proxy hands the page. The refresh token never leaves the server. */
export interface AccessGrant {
  access_token: string;
  expires_in: number;
}

export interface Session {
  id: string;
  status: string;
  transport: string;
  started_at: string;
  ended_at: string | null;
  turn_count: number;
}

export interface PaginatedSessions {
  items: Session[];
  total: number;
}

export interface Message {
  id: string;
  turn_index: number;
  seq: number;
  role: "user" | "assistant" | string;
  content: string;
  language: string | null;
  was_interrupted: boolean;
  spoken_prefix_chars: number | null;
  latency_ms: Record<string, number>;
  created_at: string;
}

export interface TurnSummary {
  turn_index: number;
  stop_reason: string;
  interrupted: boolean;
  language: string | null;
  latency_ms: Record<string, number>;
  estimated_cost_usd: number;
  token_usage: Record<string, unknown>;
}

export interface LatencyStats {
  llm_ttft_ms_avg: number;
  sample_size: number;
}

export interface ToolUsageRow {
  tool_name: string;
  ok?: number;
  error?: number;
  rejected?: number;
  timeout?: number;
  budget_exceeded?: number;
}

export interface AdminDashboard {
  active_sessions: number;
  total_students: number;
  total_sessions: number;
  total_messages: number;
  latency: LatencyStats | NotMeasured;
  stt_failures: NotMeasured;
  tool_failures: number;
  tool_rejections: number;
  rag_failures: number;
  tool_usage: ToolUsageRow[];
  mastery: { tracked_topics: number; average_mastery: number | NotMeasured };
  memory_events: { applied: number; rejected: number; total: number };
}
