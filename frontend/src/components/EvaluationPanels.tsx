"use client";

import { useCallback, useState } from "react";

import { Button, ErrorText, Section, Spinner } from "@/components/ui";
import { getEvaluation, getRunFailures } from "@/lib/api/endpoints";
import { describeError } from "@/lib/api/errors";
import type {
  EvaluationRunSummary,
  ExperimentSummary,
  FailingCase,
  RunFailures,
} from "@/lib/api/types";
import {
  decisionLabel,
  describeComparison,
  formatCount,
  formatDateTime,
  formatHeadline,
  shortHash,
} from "@/lib/format";
import { useLoad } from "@/lib/useLoad";

/**
 * EVALUATION.md §8: each configuration's latest recorded run, every decided experiment, and a run's
 * failing cases. Everything shown was recorded by the evaluation runner; the page computes nothing.
 */
export function EvaluationPanels() {
  const { data, error, reload } = useLoad(getEvaluation);

  if (data === undefined) {
    return error !== undefined ? (
      <Section title="Evaluation">
        <div className="flex flex-col items-start gap-3">
          <ErrorText>{describeError(error)}</ErrorText>
          <Button variant="secondary" onClick={reload}>
            Try again
          </Button>
        </div>
      </Section>
    ) : (
      <Spinner label="Loading evaluation runs" />
    );
  }

  return (
    <>
      <Runs runs={data.runs} />
      <Experiments experiments={data.experiments} />
    </>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-xl border border-border bg-surface p-4 text-sm text-muted">{children}</p>
  );
}

function Runs({ runs }: { runs: EvaluationRunSummary[] }) {
  const [open, setOpen] = useState<string | null>(null);

  if (runs.length === 0) {
    return (
      <Section title="Evaluation">
        <Empty>
          No evaluation run has been recorded in this database. Runs are recorded from the command
          line: <code className="font-mono">python -m eval.runner --suite voice --record</code>.
        </Empty>
      </Section>
    );
  }

  return (
    <Section
      title="Evaluation"
      note="The latest recorded run of each configuration, with what it ran on."
    >
      <div className="overflow-x-auto rounded-xl border border-border bg-surface">
        <table className="w-full min-w-[48rem] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted">
              <th scope="col" className="px-4 py-2 font-medium">
                Suite
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Results
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Cases
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                Recorded
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {runs.map((run) => (
              <RunRow
                key={run.id}
                run={run}
                open={open === run.id}
                onToggle={() => setOpen(open === run.id ? null : run.id)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function RunRow({
  run,
  open,
  onToggle,
}: {
  run: EvaluationRunSummary;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className="align-top">
        <th scope="row" className="px-4 py-3 text-left font-normal">
          <span className="font-medium">{run.suite}</span>
          {run.config_name !== run.suite ? (
            <span className="block font-mono text-xs text-muted">{run.config_name}</span>
          ) : null}
        </th>
        <td className="px-4 py-3">
          {run.headlines.length === 0 ? (
            <span className="text-muted">See the run&rsquo;s record</span>
          ) : (
            <dl className="flex flex-wrap gap-x-5 gap-y-1">
              {run.headlines.map((metric) => (
                <div key={metric.key} className="flex items-baseline gap-1.5">
                  <dt className="text-xs text-muted">{metric.label}</dt>
                  <dd className="font-medium tabular-nums">{formatHeadline(metric)}</dd>
                </div>
              ))}
            </dl>
          )}
        </td>
        <td className="px-4 py-3 tabular-nums">
          {run.case_count !== null ? formatCount(run.case_count) : "—"}
          {run.failed_count > 0 ? (
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={open}
              className="ml-2 font-medium text-danger underline decoration-dotted underline-offset-2"
            >
              {formatCount(run.failed_count)} failing
            </button>
          ) : (
            <span className="ml-2 text-muted">none failing</span>
          )}
        </td>
        <td className="px-4 py-3 text-xs text-muted">
          <span className="block">{run.finished_at ? formatDateTime(run.finished_at) : "—"}</span>
          <span className="block font-mono">
            code {shortHash(run.git_sha)}
            {run.git_dirty ? " (uncommitted changes)" : ""} · data {run.dataset_version}{" "}
            {shortHash(run.dataset_digest)}
          </span>
        </td>
      </tr>
      {open ? (
        <tr>
          <td colSpan={4} className="bg-background px-4 py-3">
            <Failures runId={run.id} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function Failures({ runId }: { runId: string }) {
  const load = useCallback(() => getRunFailures(runId), [runId]);
  const { data, error, reload } = useLoad<RunFailures>(load);

  if (data === undefined) {
    return error !== undefined ? (
      <div className="flex items-center gap-3">
        <ErrorText>{describeError(error)}</ErrorText>
        <Button variant="secondary" onClick={reload}>
          Try again
        </Button>
      </div>
    ) : (
      <Spinner label="Loading failing cases" />
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted">
        {data.cases.length < data.failed_count
          ? `The first ${data.cases.length} of ${data.failed_count} failing cases`
          : `${data.failed_count} failing ${data.failed_count === 1 ? "case" : "cases"}`}
      </p>
      <ul className="flex flex-col gap-2">
        {data.cases.map((c) => (
          <FailureItem key={c.case_id} failure={c} />
        ))}
      </ul>
    </div>
  );
}

/** A case's own words when it has them; otherwise its fields, compactly. */
function describeInput(input: Record<string, unknown>): string {
  const text = input.text ?? input.query;
  return typeof text === "string" ? text : compact(input);
}

function compact(value: unknown): string {
  if (value === null || value === undefined) return "—";
  const rendered =
    typeof value === "object" && !Array.isArray(value)
      ? Object.entries(value as Record<string, unknown>)
          .map(([key, v]) => `${key}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
          .join(" · ")
      : typeof value === "string"
        ? value
        : JSON.stringify(value);
  return rendered.length > 240 ? `${rendered.slice(0, 239)}…` : rendered;
}

function FailureItem({ failure }: { failure: FailingCase }) {
  return (
    <li className="rounded-lg border border-border bg-surface p-3 text-sm">
      <p>
        <span className="font-mono text-xs text-muted">{failure.case_id}</span>
        {failure.language ? <span className="ml-2 text-xs text-muted">{failure.language}</span> : null}
      </p>
      <p className="mt-1">{describeInput(failure.input)}</p>
      <dl className="mt-2 grid gap-1 text-xs sm:grid-cols-[6rem_1fr]">
        <dt className="text-muted">Expected</dt>
        <dd className="break-words font-mono">{compact(failure.expected)}</dd>
        <dt className="text-muted">Got</dt>
        <dd className="break-words font-mono">{compact(failure.actual)}</dd>
        {failure.notes ? (
          <>
            <dt className="text-muted">Why</dt>
            <dd className="break-words">{failure.notes}</dd>
          </>
        ) : null}
      </dl>
    </li>
  );
}

const DECISION_STYLES: Record<string, string> = {
  adopt: "border-accent text-accent",
  reject: "border-danger text-danger",
};

function Experiments({ experiments }: { experiments: ExperimentSummary[] }) {
  if (experiments.length === 0) {
    return (
      <Section title="Experiments">
        <Empty>
          No experiment has been decided in this database. An experiment is run with{" "}
          <code className="font-mono">python -m eval.runner --experiment … --record</code>.
        </Empty>
      </Section>
    );
  }
  return (
    <Section
      title="Experiments"
      note="Each decided by the rule registered before its runs: adopt, reject, or inconclusive."
    >
      <ul className="grid gap-3 lg:grid-cols-2">
        {experiments.map((e) => (
          <li key={e.slug} className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <h3 className="font-semibold">
                <span className="font-mono text-sm text-muted">{e.slug}</span> {e.title}
              </h3>
              <span
                className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${DECISION_STYLES[e.decision] ?? "border-border text-muted"}`}
              >
                {decisionLabel(e.decision)}
              </span>
            </div>
            <p className="text-sm text-muted">{e.hypothesis}</p>
            <p className="text-xs text-muted">
              Changed <span className="font-mono">{e.variable_changed}</span> · suite {e.suite}
              {e.decided_at ? ` · decided ${formatDateTime(e.decided_at)}` : ""}
            </p>
            {describeComparison(e) ? (
              <p className="font-mono text-xs">{describeComparison(e)}</p>
            ) : null}
            {e.guards.length > 0 ? (
              <ul className="flex flex-col gap-0.5 text-xs">
                {e.guards.map((g) => (
                  <li key={g.metric} className={g.failed ? "font-medium text-danger" : "text-muted"}>
                    Guard <span className="font-mono">{g.metric}</span>: loss{" "}
                    {g.mean_loss.toFixed(3)} (allowed {g.max_loss}){g.failed ? " — failed" : " — held"}
                  </li>
                ))}
              </ul>
            ) : null}
            {/* The recorded sentence repeats the comparison at full precision; kept, folded away. */}
            {e.rationale ? (
              <details className="text-xs text-muted">
                <summary className="cursor-pointer">Why, in full</summary>
                <p className="mt-1">{e.rationale}</p>
              </details>
            ) : null}
          </li>
        ))}
      </ul>
    </Section>
  );
}
