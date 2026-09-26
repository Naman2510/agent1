"use client";

import { useEffect, type ReactNode } from "react";

import { Button, ErrorText, Spinner } from "@/components/ui";
import { getAdminDashboard } from "@/lib/api/endpoints";
import { describeError } from "@/lib/api/errors";
import type { AdminDashboard as Dashboard, ToolUsageRow } from "@/lib/api/types";
import { formatCount, formatMs, toolName } from "@/lib/format";
import { useLoad } from "@/lib/useLoad";

const REFRESH_MS = 30_000;

export function AdminDashboard() {
  const { data, error, loading, reload, updatedAt } = useLoad(getAdminDashboard);

  useEffect(() => {
    const timer = setInterval(reload, REFRESH_MS);
    return () => clearInterval(timer);
  }, [reload]);

  if (data === undefined) {
    return error !== undefined ? (
      <div className="flex flex-col items-start gap-3">
        <ErrorText>{describeError(error)}</ErrorText>
        <Button variant="secondary" onClick={reload}>
          Try again
        </Button>
      </div>
    ) : (
      <Spinner label="Loading the dashboard" />
    );
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Admin</h1>
          <p className="text-sm text-muted">
            {updatedAt ? `Updated ${new Date(updatedAt).toLocaleTimeString()}` : null} · refreshes
            every 30 s
          </p>
        </div>
        <div className="flex items-center gap-3">
          {error !== undefined ? <ErrorText>Refresh failed — showing the last data.</ErrorText> : null}
          <Button variant="secondary" onClick={reload} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </Button>
        </div>
      </div>

      {/* A refetch keeps the frame: the previous numbers stay, dimmed, until the new ones land. */}
      <div
        className={`flex flex-col gap-8 transition-opacity ${loading ? "opacity-60" : ""}`}
        aria-busy={loading}
      >
        <Overview data={data} />
        <SpeedAndReliability data={data} />
        <ToolUsage rows={data.tool_usage} />
        <Learning data={data} />
      </div>
    </div>
  );
}

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section aria-labelledby={slug(title)} className="flex flex-col gap-3">
      <div>
        <h2 id={slug(title)} className="text-base font-semibold">
          {title}
        </h2>
        {note ? <p className="text-sm text-muted">{note}</p> : null}
      </div>
      {children}
    </section>
  );
}

const slug = (title: string) => `admin-${title.toLowerCase().replace(/\W+/g, "-")}`;

function Overview({ data }: { data: Dashboard }) {
  return (
    <Section title="Right now">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Active sessions" value={formatCount(data.active_sessions)} />
        <StatTile label="Students" value={formatCount(data.total_students)} />
        <StatTile label="Sessions, all time" value={formatCount(data.total_sessions)} />
        <StatTile label="Messages, all time" value={formatCount(data.total_messages)} />
      </div>
    </Section>
  );
}

function SpeedAndReliability({ data }: { data: Dashboard }) {
  const latency = data.latency;
  return (
    <Section title="Speed and reliability">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {latency === "not_measured" ? (
          <NotMeasuredTile label="Average first token" why="No turn has recorded timing yet." />
        ) : (
          <StatTile
            label="Average first token"
            value={formatMs(latency.llm_ttft_ms_avg)}
            detail={`across ${formatCount(latency.sample_size)} ${latency.sample_size === 1 ? "turn" : "turns"}`}
          />
        )}
        <FailureTile label="Tool failures" count={data.tool_failures} />
        <FailureTile
          label="Course-search failures"
          count={data.rag_failures}
          note="Included in tool failures"
        />
        <StatTile
          label="Tool calls refused"
          value={formatCount(data.tool_rejections)}
          detail="Blocked by policy, not broken"
        />
        <NotMeasuredTile
          label="Speech-recognition failures"
          why="Nothing records these yet."
        />
      </div>
    </Section>
  );
}

function StatTile({ label, value, detail }: { label: string; value: string; detail?: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {detail ? <p className="mt-1 text-xs text-muted">{detail}</p> : null}
    </div>
  );
}

/** A count that is bad news when it is not zero: then it carries a status icon and a label too. */
function FailureTile({ label, count, note }: { label: string; count: number; note?: string }) {
  return (
    <StatTile
      label={label}
      value={formatCount(count)}
      detail={
        <>
          {count > 0 ? (
            <span className="flex items-center gap-1 font-medium text-danger">
              <AlertIcon />
              Needs a look
            </span>
          ) : note ? null : (
            "None recorded"
          )}
          {note ? <span className="block">{note}</span> : null}
        </>
      }
    />
  );
}

/** "Not measured" is not zero: a zero would claim a measurement that does not exist. */
function NotMeasuredTile({ label, why }: { label: string; why: string }) {
  return (
    <StatTile
      label={label}
      value="—"
      detail={
        <>
          <span className="font-medium">Not measured.</span> {why}
        </>
      }
    />
  );
}

function AlertIcon() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="currentColor">
      <path d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Zm-.75 3.25h1.5v4.5h-1.5v-4.5Zm0 5.75h1.5V12h-1.5v-1.5Z" />
    </svg>
  );
}

const OUTCOMES = [
  { key: "error", label: "Errors" },
  { key: "timeout", label: "Timed out" },
  { key: "budget_exceeded", label: "Over budget" },
  { key: "rejected", label: "Refused" },
] as const;

function callsOf(row: ToolUsageRow): number {
  return (row.ok ?? 0) + OUTCOMES.reduce((sum, { key }) => sum + (row[key] ?? 0), 0);
}

function ToolUsage({ rows }: { rows: ToolUsageRow[] }) {
  if (rows.length === 0) {
    return (
      <Section title="Tools">
        <p className="rounded-xl border border-border bg-surface p-4 text-sm text-muted">
          No tool calls yet. They appear once students ask for course material, progress, plans or
          quizzes.
        </p>
      </Section>
    );
  }
  const sorted = [...rows].sort((a, b) => callsOf(b) - callsOf(a) || a.tool_name.localeCompare(b.tool_name));
  const most = Math.max(...sorted.map(callsOf), 1);

  return (
    <Section title="Tools" note="Every call the mentor made, by outcome.">
      <div className="overflow-x-auto rounded-xl border border-border bg-surface">
        <table className="w-full min-w-[40rem] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted">
              <th scope="col" className="px-4 py-2 font-medium">
                Tool
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Calls
              </th>
              <th scope="col" className="px-4 py-2 text-right font-medium">
                OK
              </th>
              {OUTCOMES.map(({ key, label }) => (
                <th key={key} scope="col" className="px-4 py-2 text-right font-medium">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {sorted.map((row) => {
              const calls = callsOf(row);
              return (
                <tr key={row.tool_name}>
                  <th scope="row" className="px-4 py-2 text-left font-normal">
                    <span className="font-medium">{toolName(row.tool_name)}</span>{" "}
                    <span className="font-mono text-xs text-muted">{row.tool_name}</span>
                  </th>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-3">
                      <span className="w-10 text-right tabular-nums">{formatCount(calls)}</span>
                      {/* One series, one colour: bar length is calls relative to the busiest tool. */}
                      <span aria-hidden className="block h-2 w-28">
                        <span
                          className="block h-2 rounded-r-[4px] bg-accent"
                          style={{ width: `${Math.max((calls / most) * 100, calls > 0 ? 2 : 0)}%` }}
                        />
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">{formatCount(row.ok ?? 0)}</td>
                  {OUTCOMES.map(({ key }) => {
                    const count = row[key] ?? 0;
                    const bad = count > 0 && key !== "rejected";
                    return (
                      <td
                        key={key}
                        className={`px-4 py-2 text-right tabular-nums ${bad ? "font-medium text-danger" : count > 0 ? "" : "text-muted"}`}
                      >
                        {formatCount(count)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function Learning({ data }: { data: Dashboard }) {
  const { mastery, memory_events: memory } = data;
  return (
    <Section title="Learning">
      <div className="grid gap-3 lg:grid-cols-3">
        <StatTile
          label="Topics being tracked"
          value={formatCount(mastery.tracked_topics)}
          detail="Across all students"
        />
        <div className="rounded-xl border border-border bg-surface p-4">
          {mastery.average_mastery === "not_measured" ? (
            <>
              <p className="text-sm text-muted">Average mastery</p>
              <p className="mt-1 text-2xl font-semibold">—</p>
              <p className="mt-1 text-xs text-muted">
                <span className="font-medium">Not measured.</span> No topic has a score yet.
              </p>
            </>
          ) : (
            <Meter
              label="Average mastery"
              fraction={mastery.average_mastery}
              display={`${Math.round(mastery.average_mastery * 100)}%`}
              detail="Mean score over every tracked topic"
            />
          )}
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          {memory.total === 0 ? (
            <>
              <p className="text-sm text-muted">Memory updates accepted</p>
              <p className="mt-1 text-2xl font-semibold">—</p>
              <p className="mt-1 text-xs text-muted">No memory updates proposed yet.</p>
            </>
          ) : (
            <Meter
              label="Memory updates accepted"
              fraction={memory.applied / memory.total}
              display={`${Math.round((memory.applied / memory.total) * 100)}%`}
              detail={`${formatCount(memory.applied)} of ${formatCount(memory.total)}; ${formatCount(memory.rejected)} held back by the confidence gate`}
            />
          )}
        </div>
      </div>
    </Section>
  );
}

function Meter({
  label,
  fraction,
  display,
  detail,
}: {
  label: string;
  fraction: number;
  display: string;
  detail: string;
}) {
  const clamped = Math.min(Math.max(fraction, 0), 1);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm text-muted">{label}</p>
        <p className="text-2xl font-semibold">{display}</p>
      </div>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(clamped * 100)}
        aria-valuetext={display}
        className="mt-3 h-2 w-full rounded-[4px] bg-accent-track"
      >
        <div className="h-2 rounded-r-[4px] bg-accent" style={{ width: `${clamped * 100}%` }} />
      </div>
      <p className="mt-2 text-xs text-muted">{detail}</p>
    </div>
  );
}
