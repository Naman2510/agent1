"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import { Button, Card, ErrorText, Spinner } from "@/components/ui";
import { createSession, listSessions } from "@/lib/api/endpoints";
import { describeError } from "@/lib/api/errors";
import type { Session } from "@/lib/api/types";
import { formatDateTime, formatDuration } from "@/lib/format";
import { useLoad } from "@/lib/useLoad";

const PAGE = 20;

export function StartSession() {
  const router = useRouter();
  const [pending, setPending] = useState<"websocket" | "text" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function start(transport: "websocket" | "text") {
    setPending(transport);
    setError(null);
    try {
      const session = await createSession(transport);
      router.push(`/sessions/${session.id}`);
    } catch (caught) {
      setError(describeError(caught));
      setPending(null);
    }
  }

  return (
    <div className="flex flex-col items-start gap-2 sm:items-end">
      <div className="flex gap-2">
        <Button onClick={() => void start("websocket")} disabled={pending !== null}>
          {pending === "websocket" ? "Starting…" : "Start talking"}
        </Button>
        <Button variant="secondary" onClick={() => void start("text")} disabled={pending !== null}>
          {pending === "text" ? "Starting…" : "Type instead"}
        </Button>
      </div>
      <ErrorText>{error}</ErrorText>
    </div>
  );
}

export function SessionList() {
  const [offset, setOffset] = useState(0);
  const load = useCallback(() => listSessions(PAGE, offset), [offset]);
  const { data, error, loading, reload } = useLoad(load);

  if (error !== undefined && data === undefined) {
    return (
      <Card>
        <ErrorText>{describeError(error)}</ErrorText>
        <Button variant="secondary" className="mt-3" onClick={reload}>
          Try again
        </Button>
      </Card>
    );
  }
  if (data === undefined) return <Spinner label="Loading your sessions" />;
  if (data.total === 0) {
    return (
      <Card className="text-center">
        <p className="font-medium">No conversations yet</p>
        <p className="mt-1 text-sm text-muted">
          Start one and ask anything from your syllabus — in English, Hindi, Tamil, or a mix.
        </p>
      </Card>
    );
  }

  const last = Math.min(offset + data.items.length, data.total);
  return (
    <div className="flex flex-col gap-3" aria-busy={loading}>
      <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface">
        {data.items.map((session) => (
          <SessionRow key={session.id} session={session} />
        ))}
      </ul>
      {data.total > PAGE ? (
        <div className="flex items-center justify-between text-sm text-muted">
          <span>
            {offset + 1}–{last} of {data.total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={offset === 0 || loading}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}
            >
              Newer
            </Button>
            <Button
              variant="secondary"
              disabled={last >= data.total || loading}
              onClick={() => setOffset(offset + PAGE)}
            >
              Older
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TransportIcon({ transport }: { transport: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="h-5 w-5 shrink-0 text-muted"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {transport === "text" ? (
        <>
          <rect x="2.5" y="6" width="19" height="12" rx="2" />
          <path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10" />
        </>
      ) : (
        <>
          <rect x="9" y="3" width="6" height="11" rx="3" />
          <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />
        </>
      )}
    </svg>
  );
}

const STATUS_STYLE: Record<string, string> = {
  active: "bg-accent/15 text-accent",
  ended: "bg-border text-muted",
  abandoned: "bg-border text-muted",
  error: "bg-danger/10 text-danger",
};

function SessionRow({ session }: { session: Session }) {
  const duration = formatDuration(session.started_at, session.ended_at);
  return (
    <li>
      <Link
        href={`/sessions/${session.id}`}
        className="flex items-center gap-4 px-4 py-3 hover:bg-background focus-visible:bg-background focus-visible:outline-none"
      >
        <TransportIcon transport={session.transport} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{formatDateTime(session.started_at)}</p>
          <p className="text-xs text-muted">
            {session.transport === "text" ? "Typed" : "Voice"} ·{" "}
            {session.turn_count === 1 ? "1 question" : `${session.turn_count} questions`}
            {duration ? ` · ${duration}` : ""}
          </p>
        </div>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[session.status] ?? STATUS_STYLE.ended}`}
        >
          {session.status}
        </span>
      </Link>
    </li>
  );
}
