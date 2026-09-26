"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { TextPanel } from "@/components/TextPanel";
import { Transcript } from "@/components/Transcript";
import { VoicePanel } from "@/components/VoicePanel";
import { Button, Card, ErrorText, Spinner } from "@/components/ui";
import { endSession, getSession, listMessages } from "@/lib/api/endpoints";
import { ApiError, describeError } from "@/lib/api/errors";
import { formatDateTime, formatDuration } from "@/lib/format";
import { useLoad } from "@/lib/useLoad";

export function SessionView({ id }: { id: string }) {
  return (
    <RequireAuth>
      {(me) => (
        <AppShell me={me}>
          <SessionDetail id={id} />
        </AppShell>
      )}
    </RequireAuth>
  );
}

function SessionDetail({ id }: { id: string }) {
  const load = useCallback(
    () => Promise.all([getSession(id), listMessages(id)] as const),
    [id],
  );
  const { data, error, reload } = useLoad(load);
  const [ending, setEnding] = useState(false);
  const [endError, setEndError] = useState<string | null>(null);

  if (error !== undefined && data === undefined) {
    const missing = error instanceof ApiError && error.status === 404;
    return (
      <Card>
        <p className="font-medium">{missing ? "Session not found" : "Couldn’t load this session"}</p>
        {missing ? null : <ErrorText>{describeError(error)}</ErrorText>}
        <Link href="/" className="mt-3 inline-block text-sm text-accent hover:underline">
          ← All sessions
        </Link>
      </Card>
    );
  }
  if (data === undefined) return <Spinner label="Loading the session" />;

  const [session, messages] = data;
  const active = session.status === "active";
  const duration = formatDuration(session.started_at, session.ended_at);

  async function end() {
    setEnding(true);
    setEndError(null);
    try {
      await endSession(id);
      reload();
    } catch (caught) {
      setEndError(describeError(caught));
    } finally {
      setEnding(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link href="/" className="text-sm text-muted hover:text-foreground">
            ← All sessions
          </Link>
          <h1 className="mt-1 text-xl font-semibold">
            {session.transport === "text" ? "Typed session" : "Voice session"}
          </h1>
          <p className="text-sm text-muted">
            {formatDateTime(session.started_at)}
            {duration ? ` · ${duration}` : ""} · {session.status}
          </p>
        </div>
        {active ? (
          <div className="flex flex-col items-start gap-2 sm:items-end">
            <Button variant="secondary" onClick={() => void end()} disabled={ending}>
              {ending ? "Ending…" : "End session"}
            </Button>
            <ErrorText>{endError}</ErrorText>
          </div>
        ) : null}
      </div>
      {active ? (
        session.transport === "text" ? (
          <TextPanel sessionId={id} onTurnFinished={reload} />
        ) : (
          <VoicePanel sessionId={id} onTurnFinished={reload} />
        )
      ) : null}
      <Transcript messages={messages} />
    </div>
  );
}
