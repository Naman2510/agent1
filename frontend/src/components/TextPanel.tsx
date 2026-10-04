"use client";

import { useRef, useState } from "react";

import { TypedQuestion } from "@/components/VoicePanel";
import { Card, ErrorText } from "@/components/ui";
import { sendTextTurn } from "@/lib/api/endpoints";
import { describeError } from "@/lib/api/errors";

/** The typed session: the same mentor over server-sent events, for quiet rooms and no microphone. */
export function TextPanel({
  sessionId,
  onTurnFinished,
}: {
  sessionId: string;
  onTurnFinished: () => void;
}) {
  const [question, setQuestion] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  async function ask(text: string) {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setQuestion(text);
    setReply("");
    setError(null);
    setPending(true);
    try {
      await sendTextTurn(sessionId, text, {
        onDelta: (delta) => setReply((current) => current + delta),
        signal: controller.signal,
      });
      setQuestion(null);
      setReply("");
    } catch (caught) {
      if (!controller.signal.aborted) setError(describeError(caught));
    } finally {
      setPending(false);
      // Stored either way — a failed turn is part of the record too.
      onTurnFinished();
    }
  }

  return (
    <Card className="flex flex-col gap-4">
      {question ? (
        <div className="flex flex-col gap-2 text-sm" aria-live="polite">
          <p>
            <span className="font-medium text-muted">You: </span>
            {question}
          </p>
          <p>
            <span className="font-medium text-accent">Mentor: </span>
            {reply || (pending ? "…" : "")}
          </p>
        </div>
      ) : null}
      <ErrorText>{error}</ErrorText>
      <TypedQuestion
        disabled={pending}
        onSend={(text) => void ask(text)}
        placeholder="Ask your question"
      />
    </Card>
  );
}
