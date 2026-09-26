"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from "react";

import { Button, Card, ErrorText } from "@/components/ui";
import { formatMs, toolActivityLabel } from "@/lib/format";
import { VoiceClient, type TurnDetails, type VoiceSnapshot } from "@/lib/voice/client";
import type { CitationFrame } from "@/lib/voice/protocol";

const STATE_LABEL: Record<VoiceSnapshot["state"], string> = {
  idle: "Connecting…",
  listening: "Listening — ask anything",
  user_speaking: "Hearing you…",
  thinking: "Thinking…",
  speaking: "Speaking",
  barged_in: "Stopping…",
  error: "That didn’t work",
};

export function VoicePanel({
  sessionId,
  onTurnFinished,
}: {
  sessionId: string;
  onTurnFinished: () => void;
}) {
  const [client] = useState(() => new VoiceClient(sessionId));
  const snapshot = useSyncExternalStore(client.subscribe, client.getSnapshot, client.getSnapshot);

  useEffect(() => () => client.close(), [client]);

  const finished = useRef(snapshot.finishedTurns);
  useEffect(() => {
    if (snapshot.finishedTurns !== finished.current) {
      finished.current = snapshot.finishedTurns;
      onTurnFinished();
    }
  }, [snapshot.finishedTurns, onTurnFinished]);

  if (snapshot.connection === "idle" || snapshot.connection === "closed") {
    return (
      <Card>
        <p className="font-medium">
          {snapshot.connection === "idle" ? "Ready when you are" : "Voice is off"}
        </p>
        <p className="mt-1 text-sm text-muted">
          Speak in English, Hindi, Tamil or a mix. Headphones help — without them the mentor can
          hear itself.
        </p>
        <ErrorText>{snapshot.closeReason}</ErrorText>
        <Button className="mt-4" onClick={() => void client.start()}>
          {snapshot.connection === "idle" ? "Start talking" : "Reconnect"}
        </Button>
      </Card>
    );
  }

  const speaking = snapshot.state === "speaking" || snapshot.state === "thinking";
  return (
    <Card className="flex flex-col gap-5">
      <div className="flex items-center gap-4">
        <StateOrb snapshot={snapshot} />
        <div className="min-w-0 flex-1">
          <p aria-live="polite" className="font-medium">
            {snapshot.connection === "connecting" ? "Connecting…" : STATE_LABEL[snapshot.state]}
          </p>
          <p className="text-xs text-muted">
            {snapshot.mic === "blocked"
              ? "Microphone blocked — type below, or allow it in your browser."
              : snapshot.muted
                ? "Microphone muted"
                : snapshot.mic === "on"
                  ? "Microphone on"
                  : "Starting microphone…"}
          </p>
        </div>
        <div className="flex gap-2">
          {speaking ? (
            <Button variant="danger" onClick={() => client.interrupt()}>
              Stop
            </Button>
          ) : null}
          {snapshot.mic === "on" ? (
            <Button
              variant="secondary"
              aria-pressed={snapshot.muted}
              onClick={() => client.setMuted(!snapshot.muted)}
            >
              {snapshot.muted ? "Unmute" : "Mute"}
            </Button>
          ) : null}
          <Button variant="secondary" onClick={() => client.close()}>
            Hang up
          </Button>
        </div>
      </div>

      <Captions snapshot={snapshot} />
      {snapshot.error ? <ErrorText>{snapshot.error.message}</ErrorText> : null}
      {snapshot.details ? <TurnInfo details={snapshot.details} /> : null}
      <TypedQuestion
        disabled={snapshot.connection !== "open"}
        onSend={(text) => client.sendText(text)}
      />
    </Card>
  );
}

function StateOrb({ snapshot }: { snapshot: VoiceSnapshot }) {
  const listening = snapshot.state === "listening" || snapshot.state === "user_speaking";
  const scale = listening && !snapshot.muted ? 1 + snapshot.level * 0.6 : 1;
  const tone =
    snapshot.state === "speaking"
      ? "bg-accent"
      : snapshot.state === "thinking"
        ? "bg-accent/60 animate-pulse"
        : snapshot.state === "error"
          ? "bg-danger"
          : "bg-accent/30";
  return (
    <div aria-hidden className="flex h-14 w-14 shrink-0 items-center justify-center">
      <div
        className={`h-10 w-10 rounded-full transition-transform duration-100 ${tone}`}
        style={{ transform: `scale(${scale})` }}
      />
    </div>
  );
}

function Captions({ snapshot }: { snapshot: VoiceSnapshot }) {
  if (!snapshot.heard && !snapshot.reply) {
    return <p className="text-sm text-muted">Your words and the mentor’s reply appear here.</p>;
  }
  return (
    <div className="flex flex-col gap-2 text-sm">
      {snapshot.heard ? (
        <p>
          <span className="font-medium text-muted">You: </span>
          {snapshot.heard}
        </p>
      ) : null}
      {snapshot.reply ? (
        <p>
          <span className="font-medium text-accent">Mentor: </span>
          {snapshot.reply}
          {snapshot.interrupted ? <span className="text-muted"> — stopped</span> : null}
        </p>
      ) : null}
    </div>
  );
}

function TurnInfo({ details }: { details: TurnDetails }) {
  const latency = details.latencyMs ?? {};
  const stages = [
    ["You stopped → first audio", latency.ttfa_ms],
    ["Speech recognised", latency.stt_final_ms],
    ["First word written", latency.llm_ttft_ms],
    ["First sound made", latency.tts_ttfb_ms],
  ].filter((stage): stage is [string, number] => typeof stage[1] === "number");

  return (
    <div className="flex flex-col gap-3 border-t border-border pt-4 text-sm">
      {details.tools.length > 0 ? (
        <ul className="flex flex-wrap gap-2" aria-label="What the mentor did">
          {details.tools.map((tool, index) => (
            <li
              key={`${tool.tool_name}-${index}`}
              className={`rounded-full px-2.5 py-0.5 text-xs ${tool.ok ? "bg-accent/10 text-accent" : "bg-danger/10 text-danger"}`}
            >
              {toolActivityLabel(tool.tool_name)}
              {tool.ok ? "" : " (failed)"}
            </li>
          ))}
        </ul>
      ) : null}
      {details.citations.length > 0 ? (
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted">Sources</p>
          <ol className="mt-1 flex flex-col gap-1">
            {details.citations.map((citation) => (
              <li key={citation.ref}>
                <span className="font-mono text-xs text-muted">{citation.ref}</span>{" "}
                {describeCitation(citation)}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {stages.length > 0 ? (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-muted sm:grid-cols-4">
          {stages.map(([label, ms]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd className="font-medium text-foreground">{formatMs(ms)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

function describeCitation(citation: CitationFrame): string {
  const where = citation.heading_path ?? citation.section;
  const pages =
    citation.page_start === null
      ? null
      : citation.page_end !== null && citation.page_end !== citation.page_start
        ? `pp. ${citation.page_start}–${citation.page_end}`
        : `p. ${citation.page_start}`;
  return [citation.document_title, where, pages].filter(Boolean).join(" — ");
}

export function TypedQuestion({
  disabled,
  onSend,
  placeholder = "Or type your question",
}: {
  disabled: boolean;
  onSend: (text: string) => void;
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setText("");
  }
  return (
    <form onSubmit={submit} className="flex gap-2">
      <label htmlFor="typed-question" className="sr-only">
        {placeholder}
      </label>
      <input
        id="typed-question"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder={placeholder}
        maxLength={2000}
        disabled={disabled}
        className="min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/30 disabled:opacity-50"
      />
      <Button type="submit" variant="secondary" disabled={disabled || !text.trim()}>
        Send
      </Button>
    </form>
  );
}
