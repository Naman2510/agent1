"""Prompt-injection defense suite (Gate 6, DATASET.md §2's "Prompt-injection" slice).

This does **not** measure whether a real model resists an injected instruction — that would need
a real LLM call, and this sandbox has none (no Anthropic API key; see EVALUATION.md §5.1's
agent-suite caveat, which applies here for the same reason). Instead every case scripts the
*worst* case directly: assume the model has already been fully persuaded by the injected text and
is now requesting exactly the tool call an attacker wants, with exactly the arguments an attacker
wants. What this suite measures is whether the system-level defenses ARCHITECTURE §8.4 describes —
the intent allowlist enforced at the executor, and no tool input model ever accepting identity as
an argument — still stop that call from ever reaching a handler.

A case's injected text (embedded in a retrieved document, or written into the user's own
utterance) is documentation of the attack shape, not something read by code here: nothing in this
suite parses `injected_text` or `legitimate_utterance`, because nothing here runs a model that
could be swayed by them. The suite is only as good as the belief that `attempted_calls` accurately
represents what a successfully-injected model would try — see PHASE_6_AUDIT.md for that judgement
call written out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agent.intent import INTENT_TOOLS, Intent
from app.agent.tools.base import ToolContext
from app.agent.tools.executor import execute_tool_call
from app.agent.tools.registry import ToolRegistry
from app.providers.llm.base import ToolCall

ExpectedDefense = str  # "not_in_allowlist" | "schema_rejected" | "unknown_tool"


@dataclass(frozen=True)
class AttemptedCall:
    tool: str
    arguments: dict[str, Any]
    expected_defense: ExpectedDefense


@dataclass(frozen=True)
class InjectionCase:
    id: str
    category: str
    injection_site: str
    intent_context: str
    legitimate_utterance: str
    injected_text: str | None
    attempted_calls: list[AttemptedCall]
    note: str


def load_cases(path: Path) -> list[InjectionCase]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cases.append(
            InjectionCase(
                id=row["id"],
                category=row["category"],
                injection_site=row["injection_site"],
                intent_context=row["intent_context"],
                legitimate_utterance=row["legitimate_utterance"],
                injected_text=row.get("injected_text"),
                attempted_calls=[AttemptedCall(**c) for c in row["attempted_calls"]],
                note=row["note"],
            )
        )
    return cases


@dataclass(frozen=True)
class CallOutcome:
    case_id: str
    tool: str
    expected_defense: ExpectedDefense
    blocked: bool
    message: str


@dataclass
class InjectionReport:
    outcomes: list[CallOutcome] = field(default_factory=list)

    def add(self, outcome: CallOutcome) -> None:
        self.outcomes.append(outcome)

    @property
    def executed(self) -> list[CallOutcome]:
        """Every attempted call that was NOT blocked — Gate 6 requires this to be empty."""
        return [o for o in self.outcomes if not o.blocked]

    def summary(self) -> dict[str, int]:
        return {
            "total_attempted_calls": len(self.outcomes),
            "blocked": len(self.outcomes) - len(self.executed),
            "executed": len(self.executed),
        }

    def render(self) -> str:
        s = self.summary()
        lines = [f"{s['blocked']}/{s['total_attempted_calls']} attempted calls blocked"]
        for outcome in self.executed:
            lines.append(
                f"  NOT BLOCKED: {outcome.case_id} -> {outcome.tool} "
                f"(expected defense: {outcome.expected_defense})"
            )
        return "\n".join(lines)


async def run(
    cases: list[InjectionCase], *, registry: ToolRegistry, ctx: ToolContext
) -> InjectionReport:
    """Replays every attempted call as if the model had already been persuaded to make it.

    One shared `ToolContext` for the whole run is deliberate, not a shortcut: every case is
    expected to be rejected before a handler ever runs, so there is no real mutation for per-case
    isolation to protect against. If a case's own note turns out to be wrong and a call actually
    executes, that mutation becoming visible to later cases is a feature, not a bug — it is exactly
    the kind of cross-contamination a real attacker's successful call would also cause.
    """
    report = InjectionReport()
    for case in cases:
        allowed = INTENT_TOOLS[Intent(case.intent_context)]
        for index, attempt in enumerate(case.attempted_calls):
            call = ToolCall(id=f"{case.id}-{index}", name=attempt.tool, arguments=attempt.arguments)
            result = await execute_tool_call(
                call, registry=registry, ctx=ctx, allowed_tool_names=allowed
            )
            report.add(
                CallOutcome(
                    case_id=case.id,
                    tool=attempt.tool,
                    expected_defense=attempt.expected_defense,
                    blocked=result.is_error,
                    message=result.content,
                )
            )
    return report
