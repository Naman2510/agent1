"""The agent (tool-use) evaluation suite (EVALUATION.md §5.1, Gate 6).

**What this can and cannot measure.** §5.1 asks for tool-selection accuracy and task-completion
rate — both mean "did a real model pick correctly," which needs a real model. There is no
Anthropic API key in this sandbox (the same limitation already documented for STT/TTS in Phase 3
and for the injection suite in Phase 6), so nothing here scores a model's judgement. What IS real:

1. **Allowlist coverage** — for every scenario, does `IntentGate`'s allowlist for the scenario's
   intent actually contain the tools a legitimate request like it needs, and exclude the ones
   named as wrong for it? This is a regression guard on the allowlist table itself, not a claim
   about model behaviour — and it is not hypothetical: it is exactly the check that would have
   caught `update_student_progress` never being reachable from any intent, a real bug this phase
   found and fixed (ARCHITECTURE §8.2, PHASE_6_AUDIT.md).
2. **Pipeline execution** — for scenarios marked `run_pipeline`, a scripted model requests exactly
   the scenario's expected (plus any deliberately-unnecessary) tools, and the real orchestrator,
   executor, and tool handlers run against a real database. This proves the plumbing completes a
   legitimate multi-tool turn, correctly flags an unnecessary-but-allowed call, and surfaces a
   handler-raised error as a graceful result rather than crashing — all mechanical facts, none of
   them requiring a model's judgement to be true or false.
3. **Gated vs ungated exposure** — for scenarios with a `gated_vs_ungated_probe`, the same scripted
   attempt at one additional (forbidden) tool is run once under the scenario's real gated allowlist
   and once under every tool in the registry ("ungated"). This shows the gate is not a no-op: it
   measurably changes which calls execute, holding everything else fixed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.agent.intent import INTENT_TOOLS, Intent
from app.agent.orchestrator import run_agent_turn
from app.agent.tools.base import ToolContext
from app.agent.tools.executor import execute_tool_call
from app.agent.tools.registry import ToolRegistry
from app.db.models import ToolCall as ToolCallRow
from app.db.models import ToolStatus
from app.providers.llm.base import (
    Effort,
    LLMProvider,
    SystemBlock,
    ToolCall,
    TurnMessage,
)
from app.providers.llm.fake import FakeLLMProvider, ScriptedTurn

# A schema-valid minimal argument set per tool, used only for the gated-vs-ungated probe: the
# point of the probe is to isolate what gating changes, so the probed call must not fail for an
# unrelated reason (a schema mismatch would look identical to a gating block in a naive check).
_MINIMAL_VALID_ARGS: dict[str, dict[str, Any]] = {
    "search_knowledge": {"query": "anything"},
    "get_student_progress": {},
    "retrieve_previous_conversation": {},
    "generate_quiz": {
        "subject": "EMT",
        "topic": "KVL",
        "difficulty": "easy",
        "questions": [{"prompt": "State KVL.", "expected": "Sum of loop voltages is zero."}],
    },
    "update_student_progress": {"subject": "EMT", "topic": "KVL", "correct": 1, "total": 1},
    "create_study_plan": {
        "title": "Probe plan",
        "start_date": "2026-09-22",
        "end_date": "2026-09-23",
        "items": [{"day_index": 0, "subject": "EMT", "topic": "KVL", "activity": "revise"}],
    },
    "get_study_plan": {},
}

_SYSTEM = (SystemBlock(text="You are VaaniOS, a mentor.", cacheable=True),)


@dataclass(frozen=True)
class AgentScenario:
    id: str
    category: str
    utterance: str
    intent_context: str
    expected_tools: list[str]
    unnecessary_tools: list[str]
    forbidden_tools: list[str]
    tool_arguments: dict[str, dict[str, Any]]
    run_pipeline: bool
    gated_vs_ungated_probe: str | None
    expect_tool_error: bool
    final_reply: str
    note: str | None


def load_cases(path: Path) -> list[AgentScenario]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cases.append(AgentScenario(**row))
    return cases


@dataclass(frozen=True)
class AllowlistCheck:
    scenario_id: str
    ok: bool
    missing_expected: frozenset[str]
    wrongly_allowed_forbidden: frozenset[str]


def check_allowlist_coverage(scenario: AgentScenario) -> AllowlistCheck:
    """Pure, DB-free: does this scenario's own allowlist actually support the task it names?"""
    allowed = INTENT_TOOLS[Intent(scenario.intent_context)]
    missing = frozenset(scenario.expected_tools) - allowed
    wrongly_allowed = frozenset(scenario.forbidden_tools) & allowed
    return AllowlistCheck(
        scenario_id=scenario.id,
        ok=not missing and not wrongly_allowed,
        missing_expected=missing,
        wrongly_allowed_forbidden=wrongly_allowed,
    )


@dataclass(frozen=True)
class PipelineOutcome:
    scenario_id: str
    completed: bool
    executed_tools: frozenset[str]
    forbidden_tools_executed: frozenset[str]
    unnecessary_tools_flagged: frozenset[str]
    tool_error_surfaced: bool


def _scripted_llm_for(scenario: AgentScenario) -> FakeLLMProvider:
    requested = scenario.expected_tools + scenario.unnecessary_tools
    if not requested:
        # Nothing to call (e.g. a CLARIFICATION/CASUAL scenario): a single end_turn reply, not an
        # artificial tool_use round with zero tool calls in it.
        return FakeLLMProvider([ScriptedTurn(text=scenario.final_reply, stop_reason="end_turn")])
    calls = [
        ToolCall(
            id=f"{scenario.id}-{i}", name=name, arguments=scenario.tool_arguments.get(name, {})
        )
        for i, name in enumerate(requested)
    ]
    return FakeLLMProvider(
        [
            ScriptedTurn(tool_calls=calls, stop_reason="tool_use"),
            ScriptedTurn(text=scenario.final_reply, stop_reason="end_turn"),
        ]
    )


async def run_pipeline_scenario(
    scenario: AgentScenario, *, registry: ToolRegistry, ctx: ToolContext
) -> PipelineOutcome:
    llm: LLMProvider = _scripted_llm_for(scenario)
    allowed = INTENT_TOOLS[Intent(scenario.intent_context)]

    outcome = None
    async for _fragment, maybe_outcome in run_agent_turn(
        llm=llm,
        system=_SYSTEM,
        initial_messages=[TurnMessage(role="user", text=scenario.utterance)],
        registry=registry,
        allowed_tool_names=allowed,
        tool_ctx=ctx,
        max_output_tokens=512,
        effort=Effort.LOW,
    ):
        if maybe_outcome is not None:
            outcome = maybe_outcome

    rows = (
        (
            await ctx.db.execute(
                select(ToolCallRow).where(
                    ToolCallRow.session_id == ctx.session_id,
                    ToolCallRow.turn_index == ctx.turn_index,
                )
            )
        )
        .scalars()
        .all()
    )

    executed = frozenset(r.tool_name for r in rows if r.status is ToolStatus.OK)
    errored = frozenset(r.tool_name for r in rows if r.status is ToolStatus.ERROR)

    return PipelineOutcome(
        scenario_id=scenario.id,
        completed=outcome is not None and outcome.stop_reason in ("end_turn", "max_tokens"),
        executed_tools=executed,
        forbidden_tools_executed=executed & frozenset(scenario.forbidden_tools),
        unnecessary_tools_flagged=frozenset(scenario.unnecessary_tools) & executed,
        tool_error_surfaced=bool(errored) if scenario.expect_tool_error else False,
    )


@dataclass(frozen=True)
class ProbeOutcome:
    scenario_id: str
    probe_tool: str
    gated_blocked_it: bool
    ungated_executed_it: bool

    @property
    def gate_earned_its_place(self) -> bool:
        """The one thing this probe exists to show: gating changed the outcome for this call."""
        return self.gated_blocked_it and self.ungated_executed_it


async def run_gated_vs_ungated_probe(
    scenario: AgentScenario, *, registry: ToolRegistry, ctx: ToolContext
) -> ProbeOutcome:
    assert scenario.gated_vs_ungated_probe is not None
    probe = scenario.gated_vs_ungated_probe
    call = ToolCall(id=f"{scenario.id}-probe", name=probe, arguments=_MINIMAL_VALID_ARGS[probe])
    gated_allowed = INTENT_TOOLS[Intent(scenario.intent_context)]

    gated_result = await execute_tool_call(
        call, registry=registry, ctx=ctx, allowed_tool_names=gated_allowed
    )
    ungated_result = await execute_tool_call(
        call, registry=registry, ctx=ctx, allowed_tool_names=registry.all_names
    )
    return ProbeOutcome(
        scenario_id=scenario.id,
        probe_tool=probe,
        gated_blocked_it=gated_result.is_error,
        ungated_executed_it=not ungated_result.is_error,
    )


@dataclass
class AgentReport:
    allowlist_checks: list[AllowlistCheck] = field(default_factory=list)
    pipeline_outcomes: list[PipelineOutcome] = field(default_factory=list)
    probe_outcomes: list[ProbeOutcome] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "allowlist_coverage_ok": sum(1 for c in self.allowlist_checks if c.ok),
            "allowlist_coverage_total": len(self.allowlist_checks),
            "pipeline_completed": sum(1 for p in self.pipeline_outcomes if p.completed),
            "pipeline_total": len(self.pipeline_outcomes),
            "pipeline_forbidden_tool_leaked": sum(
                1 for p in self.pipeline_outcomes if p.forbidden_tools_executed
            ),
            "probes_where_gate_earned_its_place": sum(
                1 for p in self.probe_outcomes if p.gate_earned_its_place
            ),
            "probes_total": len(self.probe_outcomes),
        }

    def render(self) -> str:
        s = self.summary()
        lines = [
            f"allowlist coverage:   {s['allowlist_coverage_ok']}/{s['allowlist_coverage_total']}",
            f"pipeline completed:   {s['pipeline_completed']}/{s['pipeline_total']}",
            f"forbidden tool leaks: {s['pipeline_forbidden_tool_leaked']}",
            f"gate earned its place (gated blocked AND ungated executed): "
            f"{s['probes_where_gate_earned_its_place']}/{s['probes_total']}",
        ]
        for check in self.allowlist_checks:
            if not check.ok:
                lines.append(f"  ALLOWLIST GAP: {check.scenario_id} {check!r}")
        for outcome in self.pipeline_outcomes:
            if outcome.forbidden_tools_executed:
                lines.append(f"  FORBIDDEN EXECUTED: {outcome.scenario_id} {outcome!r}")
        return "\n".join(lines)
