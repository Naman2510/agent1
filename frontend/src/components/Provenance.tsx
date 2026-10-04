import type { Citation, ToolActivity } from "@/lib/api/types";
import { describeCitation, toolActivityLabel } from "@/lib/format";

/** What the mentor did for an answer: each tool it called, and whether that worked. */
export function ToolChips({ tools }: { tools: ToolActivity[] }) {
  if (tools.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-2" aria-label="What the mentor did">
      {tools.map((tool, index) => (
        <li
          key={`${tool.tool_name}-${index}`}
          className={`rounded-full px-2.5 py-0.5 text-xs ${tool.ok ? "bg-accent/10 text-accent" : "bg-danger/10 text-danger"}`}
        >
          {toolActivityLabel(tool.tool_name)}
          {tool.ok ? "" : " (failed)"}
        </li>
      ))}
    </ul>
  );
}

/** Where an answer came from: the course material it cited, by the [n] in its text. */
export function SourceList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-muted">Sources</p>
      <ol className="mt-1 flex flex-col gap-1" aria-label="Sources">
        {citations.map((citation) => (
          <li key={citation.ref}>
            <span className="font-mono text-xs text-muted">{citation.ref}</span>{" "}
            {describeCitation(citation)}
          </li>
        ))}
      </ol>
    </div>
  );
}
