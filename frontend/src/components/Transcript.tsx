import type { Message } from "@/lib/api/types";
import { formatMs, languageName } from "@/lib/format";

export function Transcript({ messages }: { messages: Message[] }) {
  if (messages.length === 0) {
    return <p className="text-sm text-muted">Nothing has been said in this session yet.</p>;
  }
  return (
    <ol className="flex flex-col gap-3" aria-label="Transcript">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
    </ol>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const mine = message.role === "user";
  const language = languageName(message.language);
  const firstToken = message.latency_ms?.llm_ttft_ms;
  const details = [
    language,
    !mine && typeof firstToken === "number" ? `first word in ${formatMs(firstToken)}` : null,
  ].filter(Boolean);

  return (
    <li className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          mine ? "bg-accent text-accent-foreground" : "border border-border bg-surface"
        }`}
      >
        <span className="sr-only">{mine ? "You said:" : "Mentor said:"}</span>
        {message.content ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <p className="italic opacity-70">
            {message.was_interrupted ? "Interrupted before any of it played." : "(no reply)"}
          </p>
        )}
        {message.was_interrupted && message.content ? (
          // What is stored for an interrupted answer is exactly what was heard (the playback
          // ledger's spoken prefix), so the cut shown here is the real one.
          <p className="mt-1 text-xs font-medium opacity-80">— you interrupted here</p>
        ) : null}
        {details.length > 0 ? (
          <p className={`mt-1 text-[11px] ${mine ? "opacity-80" : "text-muted"}`}>
            {details.join(" · ")}
          </p>
        ) : null}
      </div>
    </li>
  );
}
